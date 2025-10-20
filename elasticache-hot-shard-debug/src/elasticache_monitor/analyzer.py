"""Log file analysis functionality"""

from collections import Counter

from .utils import parse_monitor_line, extract_key_pattern


def analyze_log_file(filepath):
    """Analyze a single monitor log file"""
    
    stats = {
        'total_commands': 0,
        'commands_by_type': Counter(),
        'key_patterns': Counter(),
        'keys_accessed': Counter(),
        'client_ips': Counter(),
        'timestamps': [],
    }
    
    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            
            parsed = parse_monitor_line(line)
            if not parsed:
                continue
            
            stats['total_commands'] += 1
            stats['commands_by_type'][parsed['command']] += 1
            stats['client_ips'][parsed['client_ip']] += 1
            stats['timestamps'].append(parsed['timestamp'])
            
            if parsed['key']:
                stats['keys_accessed'][parsed['key'][:100]] += 1
                pattern = extract_key_pattern(parsed['key'])
                stats['key_patterns'][pattern] += 1
    
    # Calculate QPS
    if len(stats['timestamps']) > 1:
        duration = max(stats['timestamps']) - min(stats['timestamps'])
        stats['qps'] = stats['total_commands'] / duration if duration > 0 else 0
        stats['duration'] = duration
    else:
        stats['qps'] = 0
        stats['duration'] = 0
    
    return stats

