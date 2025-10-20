"""
Bandwidth estimation by sampling actual key sizes from Redis.
"""
import redis
from collections import defaultdict
from typing import Dict, List, Tuple
from colorama import Fore


class BandwidthEstimator:
    """Estimate bandwidth by sampling actual key sizes."""
    
    def __init__(self, host: str, port: int, password: str, ssl: bool = True):
        """Initialize Redis connection for sampling."""
        self.host = host
        self.port = port
        self.password = password
        self.ssl = ssl
        self.client = None
        self.pattern_sizes = {}  # Cache: pattern → avg_size_bytes
        
    def connect(self):
        """Connect to Redis."""
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                ssl=self.ssl,
                ssl_cert_reqs=None,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True
            )
            self.client.ping()
            return True
        except Exception as e:
            print(f"{Fore.RED}Error connecting to {self.host} for sampling: {e}")
            return False
    
    def sample_key_size(self, key: str) -> int:
        """Get actual size of a key in bytes using MEMORY USAGE."""
        try:
            # MEMORY USAGE returns bytes consumed in memory
            size = self.client.memory_usage(key)
            return size if size else 0
        except Exception:
            # Fallback: estimate based on key type and length
            try:
                key_type = self.client.type(key)
                if key_type == 'string':
                    strlen = self.client.strlen(key)
                    return strlen + 50  # Add overhead
                elif key_type == 'hash':
                    hlen = self.client.hlen(key)
                    return hlen * 100  # Rough estimate
                elif key_type == 'list':
                    llen = self.client.llen(key)
                    return llen * 50
                elif key_type == 'set':
                    scard = self.client.scard(key)
                    return scard * 50
                elif key_type == 'zset':
                    zcard = self.client.zcard(key)
                    return zcard * 100  # zset elements are larger
            except:
                pass
            return 1000  # Default 1KB if all else fails
    
    def sample_pattern(self, pattern: str, sample_keys: List[str], max_samples: int = 10) -> int:
        """Sample keys matching a pattern and return average size."""
        if pattern in self.pattern_sizes:
            return self.pattern_sizes[pattern]
        
        sizes = []
        sampled = 0
        
        for key in sample_keys:
            if sampled >= max_samples:
                break
            
            size = self.sample_key_size(key)
            if size > 0:
                sizes.append(size)
                sampled += 1
        
        if sizes:
            avg_size = sum(sizes) / len(sizes)
            self.pattern_sizes[pattern] = int(avg_size)
            return int(avg_size)
        
        # Fallback to default size
        return 1000
    
    def estimate_command_bandwidth(self, command: str, key: str, base_size: int, args: List[str] = None) -> int:
        """Estimate bandwidth for a specific command based on actual key size."""
        
        # Commands that return the full value
        if command in ['GET', 'DUMP', 'HGETALL', 'SMEMBERS', 'SINTER', 'SUNION']:
            return base_size
        
        # Commands that return partial data
        elif command == 'HGET':
            # Single hash field: estimate 1/N of hash size
            return max(100, base_size // 10)
        
        elif command in ['LRANGE', 'ZRANGE', 'ZREVRANGE']:
            # Parse range arguments if available
            if args and len(args) >= 2:
                try:
                    start = int(args[0])
                    stop = int(args[1])
                    if stop == -1:
                        # Full range
                        return base_size
                    else:
                        # Partial range: estimate proportion
                        range_size = stop - start + 1
                        # Assume list has ~100 elements (rough estimate)
                        return min(base_size, base_size * range_size // 100)
                except:
                    pass
            return base_size // 2  # Default: assume half the list
        
        elif command == 'MGET':
            # Multiple keys: sum of all key sizes
            # args contains the keys
            if args:
                return base_size * len(args)
            return base_size
        
        elif command in ['LPOP', 'RPOP', 'SPOP', 'ZPOPMIN', 'ZPOPMAX']:
            # Single element
            return max(50, base_size // 20)
        
        elif command in ['LLEN', 'SCARD', 'HLEN', 'ZCARD', 'EXISTS', 'TTL', 'TYPE']:
            # Small numeric responses
            return 50
        
        elif command in ['SET', 'HSET', 'LPUSH', 'RPUSH', 'SADD', 'ZADD', 'DEL', 'EXPIRE', 'INCR', 'DECR']:
            # Write commands: small acknowledgment responses
            return 30
        
        # Default: assume small response
        return 200
    
    def close(self):
        """Close Redis connection."""
        if self.client:
            try:
                self.client.close()
            except:
                pass


def estimate_shard_bandwidth(monitor_stats: Dict, host: str, port: int, password: str) -> Dict:
    """
    Estimate bandwidth for a shard by sampling actual key sizes.
    
    Args:
        monitor_stats: Statistics from ShardMonitor.get_stats()
        host: Redis host
        port: Redis port
        password: Redis password
        
    Returns:
        Dict with bandwidth estimates
    """
    estimator = BandwidthEstimator(host, port, password)
    
    if not estimator.connect():
        return {
            'estimated_bytes': 0,
            'pattern_bandwidth': {},
            'command_bandwidth': {},
            'error': 'Could not connect for sampling'
        }
    
    print(f"{Fore.CYAN}  Sampling key sizes on {monitor_stats['shard_name']}...")
    
    try:
        # Get key patterns and their sample keys
        # We need to get actual keys from monitor data
        top_keys = monitor_stats.get('top_keys', {})
        key_patterns = monitor_stats.get('top_key_patterns', {})
        commands_by_type = monitor_stats.get('commands_by_type', {})
        
        # Build pattern -> sample keys mapping
        pattern_keys = defaultdict(list)
        for key in top_keys.keys():
            # Find which pattern this key belongs to
            from .utils import extract_key_pattern
            pattern = extract_key_pattern(key)
            pattern_keys[pattern].append(key)
        
        # Sample each pattern
        pattern_bandwidth = {}
        total_bytes = 0
        
        for pattern, access_count in key_patterns.items():
            sample_keys = pattern_keys.get(pattern, [])
            if not sample_keys:
                # Use a default size if we can't sample
                avg_size = 1000
            else:
                avg_size = estimator.sample_pattern(pattern, sample_keys)
            
            estimated_bytes = avg_size * access_count
            pattern_bandwidth[pattern] = {
                'avg_size': avg_size,
                'access_count': access_count,
                'estimated_bytes': estimated_bytes
            }
            total_bytes += estimated_bytes
        
        # Estimate by command type (less accurate but useful)
        command_bandwidth = {}
        for cmd, count in commands_by_type.items():
            # Use median pattern size as baseline
            if pattern_bandwidth:
                median_size = sorted([p['avg_size'] for p in pattern_bandwidth.values()])[len(pattern_bandwidth) // 2]
            else:
                median_size = 1000
            
            # Adjust based on command
            estimated = estimator.estimate_command_bandwidth(cmd, '', median_size) * count
            command_bandwidth[cmd] = {
                'count': count,
                'estimated_bytes': estimated
            }
        
        return {
            'estimated_bytes': total_bytes,
            'estimated_mb': round(total_bytes / 1024 / 1024, 2),
            'pattern_bandwidth': pattern_bandwidth,
            'command_bandwidth': command_bandwidth,
            'pattern_sizes_cached': len(estimator.pattern_sizes)
        }
        
    except Exception as e:
        print(f"{Fore.YELLOW}  Warning: Error during sampling: {e}")
        return {
            'estimated_bytes': 0,
            'pattern_bandwidth': {},
            'command_bandwidth': {},
            'error': str(e)
        }
    finally:
        estimator.close()

