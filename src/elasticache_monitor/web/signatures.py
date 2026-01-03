"""Command signature generation for insight analysis.

Signatures compress Redis commands into analyzable patterns:
- command_signature: "LRANGE | user:{ID}:feed | 0 -1"
- arg_shape: "0 -1" (normalized argument pattern)
"""

import re
from typing import Tuple, Optional, List

# Commands that typically perform full scans (expensive)
FULL_SCAN_COMMANDS = {
    'KEYS', 'SCAN', 'HSCAN', 'SSCAN', 'ZSCAN',
    'SMEMBERS', 'HGETALL', 'LRANGE', 'ZRANGE', 'ZRANGEBYSCORE',
    'SORT', 'DEBUG'
}

# Commands that indicate lock operations
LOCK_COMMANDS = {
    'SETNX', 'WATCH', 'MULTI', 'EXEC', 'UNWATCH',
    'BLPOP', 'BRPOP', 'BLMOVE', 'BRPOPLPUSH',
    'WAIT', 'WAITAOF'
}

# SET command flags that indicate locking
LOCK_FLAGS = {'NX', 'XX'}

# Common arg patterns to normalize
ARG_NORMALIZATIONS = {
    # Range patterns
    r'^0\s+-1$': '0 -1',           # Full list range
    r'^0\s+\d+$': '0 N',           # List slice from start
    r'^-\d+\s+-1$': '-N -1',       # List slice from end
    r'^\d+\s+\d+$': 'N M',         # Generic range
    
    # Score patterns for sorted sets
    r'^-inf\s+\+inf': '-inf +inf', # Full zset range
    r'^-inf\s+[\d.]+': '-inf SCORE',
    r'^[\d.]+\s+\+inf': 'SCORE +inf',
}


def normalize_arg_shape(args: List[str], command: str) -> str:
    """
    Normalize command arguments into a pattern.
    
    Examples:
        ["key", "0", "-1"] for LRANGE -> "0 -1"
        ["key", "value", "NX", "EX", "300"] for SET -> "NX EX TTL"
        ["key", "MATCH", "*", "COUNT", "100"] for SCAN -> "MATCH * COUNT N"
    """
    if not args:
        return ""
    
    # Skip key (first arg for most commands)
    cmd = command.upper()
    
    # Commands where first arg is NOT a key
    no_key_commands = {'KEYS', 'SCAN', 'SELECT', 'AUTH', 'PING', 'INFO', 'CONFIG', 'CLIENT'}
    
    if cmd in no_key_commands:
        work_args = args
    elif len(args) > 1:
        work_args = args[1:]  # Skip key
    else:
        return ""
    
    if not work_args:
        return ""
    
    # Normalize based on command type
    if cmd in ('LRANGE', 'GETRANGE', 'SUBSTR'):
        # Range commands: normalize indices
        if len(work_args) >= 2:
            start, end = work_args[0], work_args[1]
            if start == '0' and end == '-1':
                return '0 -1'  # Full range (expensive!)
            elif start == '0':
                return '0 N'
            elif end == '-1':
                return '-N -1'
            return 'N M'
    
    elif cmd in ('ZRANGE', 'ZRANGEBYSCORE', 'ZRANGEBYLEX', 'ZREVRANGE'):
        if len(work_args) >= 2:
            start, end = work_args[0].lower(), work_args[1].lower()
            if '-inf' in start and '+inf' in end:
                return '-inf +inf'
            elif '-inf' in start:
                return '-inf SCORE'
            elif '+inf' in end:
                return 'SCORE +inf'
            return 'SCORE SCORE'
    
    elif cmd == 'SET':
        # Extract SET flags: NX, XX, EX, PX, EXAT, PXAT, KEEPTTL, GET
        flags = []
        has_ttl = False
        for i, arg in enumerate(work_args):
            upper = arg.upper()
            if upper in ('NX', 'XX', 'GET', 'KEEPTTL'):
                flags.append(upper)
            elif upper in ('EX', 'PX', 'EXAT', 'PXAT'):
                flags.append(upper)
                has_ttl = True
        if has_ttl and flags:
            return ' '.join(sorted(flags))
        return ' '.join(flags) if flags else 'VAL'
    
    elif cmd in ('SCAN', 'HSCAN', 'SSCAN', 'ZSCAN'):
        # Extract MATCH and COUNT
        parts = []
        i = 0
        while i < len(work_args):
            upper = work_args[i].upper()
            if upper == 'MATCH':
                if i + 1 < len(work_args):
                    pattern = work_args[i + 1]
                    if pattern == '*':
                        parts.append('MATCH *')
                    else:
                        parts.append('MATCH pattern')
                    i += 2
                    continue
            elif upper == 'COUNT':
                parts.append('COUNT N')
                i += 2
                continue
            i += 1
        return ' '.join(parts) if parts else 'cursor'
    
    elif cmd in ('HGET', 'HSET', 'HDEL', 'HMGET', 'HMSET'):
        # Count number of fields
        if cmd in ('HMGET', 'HMSET', 'HDEL'):
            n_fields = len(work_args)
            if n_fields > 10:
                return f'{n_fields} fields'
            elif n_fields > 1:
                return 'N fields'
        return '1 field'
    
    elif cmd == 'MGET':
        n_keys = len(args)
        if n_keys > 10:
            return f'{n_keys} keys'
        return 'N keys'
    
    elif cmd in ('LPUSH', 'RPUSH', 'SADD', 'ZADD'):
        n_vals = len(work_args)
        if n_vals > 10:
            return f'{n_vals} vals'
        elif n_vals > 1:
            return 'N vals'
        return '1 val'
    
    elif cmd == 'KEYS':
        if args and args[0] == '*':
            return '*'
        return 'pattern'
    
    # Default: just count args
    if len(work_args) > 3:
        return f'{len(work_args)} args'
    return ''


def generate_signature(command: str, key_pattern: Optional[str], args: List[str]) -> str:
    """
    Generate a command signature for aggregation.
    
    Format: <COMMAND> | <KEY_PATTERN> | <ARG_SHAPE>
    
    Examples:
        "GET | user:{ID}:profile |"
        "LRANGE | feed:{ID} | 0 -1"
        "SET | lock:{ID} | NX EX"
        "SCAN | | MATCH * COUNT N"
    """
    cmd = command.upper()
    pattern = key_pattern or '*'
    arg_shape = normalize_arg_shape(args, cmd)
    
    # Truncate long patterns
    if len(pattern) > 40:
        pattern = pattern[:37] + '...'
    
    if arg_shape:
        return f"{cmd} | {pattern} | {arg_shape}"
    return f"{cmd} | {pattern}"


def is_full_scan_command(command: str, args: List[str]) -> bool:
    """
    Detect if command performs a full scan (expensive operation).
    """
    cmd = command.upper()
    
    # Always expensive
    if cmd in ('KEYS', 'DEBUG', 'SMEMBERS', 'HGETALL'):
        return True
    
    # Check for full range scans
    if cmd in ('LRANGE', 'ZRANGE', 'ZREVRANGE'):
        if len(args) >= 3:
            start, end = args[1], args[2]
            if start == '0' and end == '-1':
                return True
            # Large ranges
            try:
                if int(end) - int(start) > 1000:
                    return True
            except:
                pass
    
    # SCAN with MATCH * is expensive
    if cmd in ('SCAN', 'HSCAN', 'SSCAN', 'ZSCAN'):
        for i, arg in enumerate(args):
            if arg.upper() == 'MATCH' and i + 1 < len(args):
                if args[i + 1] == '*':
                    return True
    
    # SORT without LIMIT
    if cmd == 'SORT':
        has_limit = any(a.upper() == 'LIMIT' for a in args)
        if not has_limit:
            return True
    
    return False


def is_lock_operation(command: str, args: List[str]) -> bool:
    """
    Detect if command is a lock/synchronization operation.
    """
    cmd = command.upper()
    
    # Direct lock commands
    if cmd in LOCK_COMMANDS:
        return True
    
    # SET with NX (distributed lock pattern)
    if cmd == 'SET':
        for arg in args:
            if arg.upper() in ('NX', 'XX'):
                return True
    
    # Patterns in key names suggesting locks
    if len(args) > 0:
        key = args[0].lower()
        if any(p in key for p in ['lock', 'mutex', 'semaphore', 'lease']):
            return True
    
    return False


def classify_command(command: str, key_pattern: Optional[str], args: List[str]) -> Tuple[str, str, bool, bool]:
    """
    Full classification of a command.
    
    Returns:
        (command_signature, arg_shape, is_full_scan, is_lock_op)
    """
    arg_shape = normalize_arg_shape(args, command)
    signature = generate_signature(command, key_pattern, args)
    full_scan = is_full_scan_command(command, args)
    lock_op = is_lock_operation(command, args)
    
    return signature, arg_shape, full_scan, lock_op

