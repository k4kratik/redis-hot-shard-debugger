"""Shared utility functions"""

import re


def parse_monitor_line(line):
    """Parse a single monitor command line"""
    try:
        line_str = line.decode('utf-8') if isinstance(line, bytes) else line
        
        # Monitor format: timestamp [db client_ip:port] "command" "arg1" "arg2" ...
        match = re.match(
            r'([\d.]+)\s+\[(\d+)\s+([\d.:a-fA-F]+):(\d+)\]\s+"([^"]+)"(?:\s+"([^"]+)")?',
            line_str
        )
        if not match:
            return None
        
        timestamp, db, client_ip, client_port, command, first_arg = match.groups()
        
        return {
            'timestamp': float(timestamp),
            'db': db,
            'client_ip': client_ip,
            'command': command.upper(),
            'key': first_arg if first_arg else None,
            'raw': line_str
        }
    except Exception:
        return None


def extract_key_pattern(key):
    """Extract pattern from key for grouping similar keys"""
    if not key:
        return "NO_KEY"
    
    # Replace UUIDs with {UUID}
    key = re.sub(
        r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
        '{UUID}',
        key,
        flags=re.IGNORECASE
    )
    
    # Replace timestamps with {TIMESTAMP}
    key = re.sub(r'\d{10,13}', '{TIMESTAMP}', key)
    
    # Replace dates (YYYY-MM-DD) with {DATE}
    key = re.sub(r'\d{4}-\d{2}-\d{2}', '{DATE}', key)
    
    # Replace large user IDs with {USERID}
    key = re.sub(r':\d{10,}:', ':{USERID}:', key)
    key = re.sub(r':\d{10,}$', ':{USERID}', key)
    
    # Replace hashes (32+ hex chars) with {HASH}
    key = re.sub(r'\b[0-9a-f]{32,}\b', '{HASH}', key, flags=re.IGNORECASE)
    
    # Replace IPs with {IP}
    key = re.sub(r'\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b', '{IP}', key)
    
    return key

