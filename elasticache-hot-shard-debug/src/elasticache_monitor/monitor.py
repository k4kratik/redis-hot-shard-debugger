"""Shard monitoring functionality"""

import redis
import time
from collections import Counter
from threading import Event
from colorama import Fore
from datetime import datetime
from typing import Optional

from .utils import parse_monitor_line, extract_key_pattern


class ShardMonitor:
    """Monitor a single Redis/Valkey shard"""
    
    def __init__(self, host, port, password, shard_name, duration=60, 
                 db_path=None, cluster_id=None, collection_time=None):
        self.host = host
        self.port = port
        self.password = password
        self.shard_name = shard_name
        self.duration = duration
        self.stop_event = Event()
        
        # Database configuration (connection created in thread)
        self.db_path = db_path
        self.db = None  # Will be created in monitor thread
        self.cluster_id = cluster_id or "unknown"
        self.collection_time = collection_time or datetime.utcnow().isoformat()
        
        # Batch inserts for performance
        self.db_batch = []
        self.db_batch_size = 100
        
        # Statistics
        self.command_count = 0
        self.commands_by_type = Counter()
        self.key_patterns = Counter()
        self.keys_accessed = Counter()
        self.client_ips = Counter()
        self.start_time = None
        self.end_time = None
        self.monitor_lines = []
        self.error = None
        
    def connect(self):
        """Establish connection to Redis/Valkey"""
        try:
            self.client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                ssl=True,
                ssl_cert_reqs=None,
                decode_responses=False,
                socket_connect_timeout=5,
                socket_keepalive=True
            )
            # Test connection
            self.client.ping()
            return True
        except Exception as e:
            self.error = str(e)
            print(f"{Fore.RED}Error connecting to {self.shard_name} ({self.host}): {e}")
            return False
    
    def monitor(self):
        """Run MONITOR command and collect statistics"""
        if not self.connect():
            return
        
        # Create database connection in this thread if needed
        if self.db_path:
            from .database import MonitorDatabase
            try:
                self.db = MonitorDatabase(self.db_path)
            except Exception as e:
                print(f"{Fore.YELLOW}Warning: Could not initialize database in thread: {e}")
                self.db = None
        
        print(f"{Fore.GREEN}Starting monitor on {self.shard_name} ({self.host})...")
        
        self.start_time = time.time()
        
        try:
            # Use pubsub monitor - this is the proper way to use MONITOR in redis-py
            with self.client.monitor() as monitor:
                for command in monitor.listen():
                    # Check if we should stop
                    if self.stop_event.is_set():
                        break
                    
                    # Check duration
                    elapsed = time.time() - self.start_time
                    if elapsed >= self.duration:
                        break
                    
                    # Process the command
                    if isinstance(command, dict) and command.get('command'):
                        try:
                            # command is already parsed by redis-py monitor
                            cmd_string = command.get('command', '')
                            
                            # Store raw line
                            self.monitor_lines.append(str(command))
                            
                            # Parse and extract info
                            parts = cmd_string.split()
                            if parts:
                                cmd_name = parts[0].upper()
                                self.command_count += 1
                                self.commands_by_type[cmd_name] += 1
                                
                                # Extract client IP if available
                                client_info = command.get('client_address', '')
                                if client_info:
                                    client_ip = client_info.split(':')[0] if ':' in client_info else client_info
                                    self.client_ips[client_ip] += 1
                                
                                # Extract key (usually first argument after command)
                                key = None
                                pattern = None
                                if len(parts) > 1:
                                    key = parts[1]
                                    self.keys_accessed[key[:100]] += 1
                                    pattern = extract_key_pattern(key)
                                    self.key_patterns[pattern] += 1
                                
                                # Save to database if enabled
                                if self.db:
                                    self.db_batch.append({
                                        'cluster_id': self.cluster_id,
                                        'shard_name': self.shard_name,
                                        'timestamp': command.get('time', time.time()),
                                        'client_address': client_info,
                                        'command': cmd_name,
                                        'key': key,
                                        'key_pattern': pattern,
                                        'args': parts[1:] if len(parts) > 1 else [],
                                        'raw_line': str(command),
                                        'collection_time': self.collection_time
                                    })
                                    
                                    # Flush batch if full
                                    if len(self.db_batch) >= self.db_batch_size:
                                        self._flush_db_batch()
                        except Exception as parse_err:
                            # Skip parsing errors
                            pass
            
        except Exception as e:
            self.error = str(e)
            print(f"{Fore.RED}Error monitoring {self.shard_name}: {e}")
        finally:
            self.end_time = time.time()
            
            # Flush remaining database batch
            if self.db and self.db_batch:
                self._flush_db_batch()
            
            # Close database connection
            if self.db:
                try:
                    self.db.close()
                except:
                    pass
            
            try:
                self.client.close()
            except:
                pass
    
    def _flush_db_batch(self):
        """Flush batch of commands to database."""
        if self.db_batch:
            try:
                self.db.insert_batch(self.db_batch)
                self.db_batch = []
            except Exception as e:
                print(f"{Fore.YELLOW}Warning: Failed to save batch to database: {e}")
    
    def get_stats(self):
        """Return statistics dictionary"""
        duration = (self.end_time or time.time()) - (self.start_time or time.time())
        qps = self.command_count / duration if duration > 0 else 0
        
        return {
            'shard_name': self.shard_name,
            'host': self.host,
            'total_commands': self.command_count,
            'duration': duration,
            'qps': qps,
            'commands_by_type': dict(self.commands_by_type.most_common(10)),
            'top_key_patterns': dict(self.key_patterns.most_common(10)),
            'top_keys': dict(self.keys_accessed.most_common(20)),
            'unique_clients': len(self.client_ips),
            'top_clients': dict(self.client_ips.most_common(10)),
            'error': self.error
        }

