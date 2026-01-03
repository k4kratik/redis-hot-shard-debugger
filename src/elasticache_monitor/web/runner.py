"""Background task runner for Redis monitoring jobs."""

import logging
import time
import json
import redis
from datetime import datetime
from threading import Thread, Event
from typing import Optional, List, Dict, Any
from collections import Counter

from sqlalchemy.orm import Session

from .db import get_db_context, get_job_db_context, init_job_db
from .models import MonitorJob, MonitorShard, RedisCommand, KeySizeCache, JobStatus, ShardStatus
from .signatures import classify_command
from ..endpoints import get_replica_endpoints, get_all_endpoints
from ..utils import extract_key_pattern

logger = logging.getLogger("redis-monitor-web")


class WebShardMonitor:
    """Monitor a single Redis shard and store results to job-specific database."""
    
    def __init__(self, job_id: str, shard_id: str, host: str, port: int, 
                 password: str, shard_name: str, duration: int):
        self.job_id = job_id
        self.shard_id = shard_id
        self.host = host
        self.port = port
        self.password = password
        self.shard_name = shard_name
        self.duration = duration
        self.stop_event = Event()
        
        # Statistics
        self.command_count = 0
        self.commands_by_type = Counter()
        self.key_patterns = Counter()
        self.start_time = None
        self.end_time = None
        self.error = None
        
        # Redis server info (captured at start)
        self.redis_version = None
        
        # Memory info (captured at end)
        self.memory_used = None
        self.memory_max = None
        self.memory_peak = None
        self.memory_rss = None
        
        # CPU metrics from INFO (captured at start and end)
        self.cpu_sys_start = None
        self.cpu_user_start = None
        self.cpu_sys_end = None
        self.cpu_user_end = None
        
        # Batch for database inserts - larger batch = faster inserts
        self.batch = []
        self.batch_size = 500
    
    def connect(self) -> Optional[redis.Redis]:
        """Establish connection to Redis."""
        logger.info(f"{self.shard_name}: Connecting to {self.host}:{self.port}...")
        try:
            client = redis.Redis(
                host=self.host,
                port=self.port,
                password=self.password,
                ssl=True,
                ssl_cert_reqs=None,
                decode_responses=True,  # Need string responses for INFO parsing
                socket_connect_timeout=10,
                socket_keepalive=True
            )
            client.ping()
            logger.info(f"{self.shard_name}: Connected successfully, PING OK")
            return client
        except Exception as e:
            self.error = str(e)
            logger.error(f"{self.shard_name}: Connection FAILED - {e}")
            return None
    
    def _capture_cpu_info(self, client: redis.Redis) -> tuple:
        """Capture CPU metrics from INFO command.
        
        Returns (cpu_sys, cpu_user) or (None, None) on error.
        """
        try:
            info = client.info('cpu')
            cpu_sys = info.get('used_cpu_sys', 0.0)
            cpu_user = info.get('used_cpu_user', 0.0)
            return cpu_sys, cpu_user
        except Exception as e:
            logger.debug(f"{self.shard_name}: Could not get CPU info: {e}")
            return None, None
    
    def _capture_server_info(self, client: redis.Redis) -> str:
        """Capture Redis version from INFO server.
        
        Returns redis_version string or None on error.
        """
        try:
            info = client.info('server')
            return info.get('redis_version')
        except Exception as e:
            logger.debug(f"{self.shard_name}: Could not get server info: {e}")
            return None
    
    def _capture_memory_info(self, client: redis.Redis) -> dict:
        """Capture memory metrics from INFO memory.
        
        Returns dict with used, max, peak, rss (all in bytes) or empty dict on error.
        """
        try:
            info = client.info('memory')
            return {
                'used': info.get('used_memory', 0),
                'max': info.get('maxmemory', 0),  # 0 means no limit
                'peak': info.get('used_memory_peak', 0),
                'rss': info.get('used_memory_rss', 0)
            }
        except Exception as e:
            logger.debug(f"{self.shard_name}: Could not get memory info: {e}")
            return {}
    
    def monitor(self):
        """Run MONITOR command and collect data."""
        # Update shard status to connecting (in metadata DB)
        with get_db_context() as db:
            shard = db.query(MonitorShard).filter(MonitorShard.id == self.shard_id).first()
            if shard:
                shard.status = ShardStatus.connecting
                shard.started_at = datetime.utcnow()
        
        client = self.connect()
        if not client:
            with get_db_context() as db:
                shard = db.query(MonitorShard).filter(MonitorShard.id == self.shard_id).first()
                if shard:
                    shard.status = ShardStatus.failed
                    shard.error_message = self.error
            return
        
        # Capture server info at start (one-time INFO snapshot)
        self.redis_version = self._capture_server_info(client)
        if self.redis_version:
            logger.info(f"{self.shard_name}: Redis version {self.redis_version}")
        
        # Capture CPU info at start (one-time INFO snapshot)
        self.cpu_sys_start, self.cpu_user_start = self._capture_cpu_info(client)
        if self.cpu_sys_start is not None:
            logger.info(f"{self.shard_name}: CPU at start - sys: {self.cpu_sys_start:.2f}s, user: {self.cpu_user_start:.2f}s")
        
        # Update to monitoring status
        with get_db_context() as db:
            shard = db.query(MonitorShard).filter(MonitorShard.id == self.shard_id).first()
            if shard:
                shard.status = ShardStatus.monitoring
                shard.redis_version = self.redis_version
                shard.cpu_sys_start = self.cpu_sys_start
                shard.cpu_user_start = self.cpu_user_start
        
        logger.info(f"Starting monitor on {self.shard_name} ({self.host}:{self.port}) for {self.duration}s...")
        self.start_time = time.time()
        
        try:
            with client.monitor() as monitor:
                for command in monitor.listen():
                    if self.stop_event.is_set():
                        logger.info(f"{self.shard_name}: Stop event received after {self.command_count} commands")
                        break
                    
                    elapsed = time.time() - self.start_time
                    if elapsed >= self.duration:
                        logger.info(f"{self.shard_name}: Duration {self.duration}s reached, captured {self.command_count} commands")
                        break
                    
                    if isinstance(command, dict) and command.get('command'):
                        self._process_command(command)
                    
                    # Log progress every 50000 commands (reduced noise)
                    if self.command_count > 0 and self.command_count % 50000 == 0:
                        logger.info(f"{self.shard_name}: {self.command_count:,} commands captured")
        
        except Exception as e:
            self.error = str(e)
            logger.error(f"Error monitoring {self.shard_name}: {e}")
        
        finally:
            self.end_time = time.time()
            actual_duration = (self.end_time - self.start_time) if self.start_time else 0
            
            # Capture CPU info at end (one-time INFO snapshot)
            self.cpu_sys_end, self.cpu_user_end = self._capture_cpu_info(client)
            if self.cpu_sys_end is not None:
                logger.info(f"{self.shard_name}: CPU at end - sys: {self.cpu_sys_end:.2f}s, user: {self.cpu_user_end:.2f}s")
            
            # Capture memory info at end
            mem_info = self._capture_memory_info(client)
            if mem_info:
                self.memory_used = mem_info.get('used')
                self.memory_max = mem_info.get('max')
                self.memory_peak = mem_info.get('peak')
                self.memory_rss = mem_info.get('rss')
                logger.info(f"{self.shard_name}: Memory - used: {self.memory_used / 1024 / 1024:.1f}MB, peak: {self.memory_peak / 1024 / 1024:.1f}MB")
            
            logger.info(f"{self.shard_name}: Monitor ended - actual duration: {actual_duration:.1f}s, commands: {self.command_count}")
            
            if self.command_count == 0:
                logger.warning(f"{self.shard_name}: NO COMMANDS CAPTURED! This could mean:")
                logger.warning(f"  - No traffic on this shard during monitoring")
                logger.warning(f"  - Connection issue with MONITOR command")
                logger.warning(f"  - Wrong endpoint (not receiving traffic)")
            
            # Update to finalizing status
            with get_db_context() as db:
                shard = db.query(MonitorShard).filter(MonitorShard.id == self.shard_id).first()
                if shard:
                    shard.status = ShardStatus.finalizing
            
            # Flush remaining batch to job-specific DB
            if self.batch:
                logger.info(f"{self.shard_name}: Flushing {len(self.batch)} remaining commands to database...")
                self._flush_batch()
            
            # Update shard status to completed
            duration = actual_duration
            qps = self.command_count / duration if duration > 0 else 0
            
            # Calculate CPU deltas
            cpu_sys_delta = None
            cpu_user_delta = None
            if self.cpu_sys_start is not None and self.cpu_sys_end is not None:
                cpu_sys_delta = self.cpu_sys_end - self.cpu_sys_start
                cpu_user_delta = self.cpu_user_end - self.cpu_user_start
                logger.info(f"{self.shard_name}: CPU delta - sys: {cpu_sys_delta:.2f}s, user: {cpu_user_delta:.2f}s (total: {cpu_sys_delta + cpu_user_delta:.2f}s)")
            
            with get_db_context() as db:
                shard = db.query(MonitorShard).filter(MonitorShard.id == self.shard_id).first()
                if shard:
                    shard.status = ShardStatus.failed if self.error else ShardStatus.completed
                    shard.completed_at = datetime.utcnow()
                    shard.command_count = self.command_count
                    shard.qps = qps
                    # Store CPU metrics
                    shard.cpu_sys_end = self.cpu_sys_end
                    shard.cpu_user_end = self.cpu_user_end
                    shard.cpu_sys_delta = cpu_sys_delta
                    shard.cpu_user_delta = cpu_user_delta
                    # Store memory metrics
                    shard.memory_used_bytes = self.memory_used
                    shard.memory_max_bytes = self.memory_max
                    shard.memory_peak_bytes = self.memory_peak
                    shard.memory_rss_bytes = self.memory_rss
                    if self.error:
                        shard.error_message = self.error
            
            try:
                client.close()
            except:
                pass
    
    def _process_command(self, command: dict):
        """Process a single monitored command."""
        try:
            cmd_string = command.get('command', '')
            parts = cmd_string.split()
            
            if not parts:
                return
            
            cmd_name = parts[0].upper()
            self.command_count += 1
            self.commands_by_type[cmd_name] += 1
            
            # Extract client info
            client_address = command.get('client_address', '')
            client_ip = client_address.split(':')[0] if ':' in client_address else client_address
            
            # Extract key and pattern
            key = None
            pattern = None
            if len(parts) > 1:
                key = parts[1]
                pattern = extract_key_pattern(key)
                self.key_patterns[pattern] += 1
            
            # Generate command signature and classify
            signature, arg_shape, is_full_scan, is_lock_op = classify_command(
                cmd_name, pattern, parts
            )
            
            # Add to batch (no job_id needed - it's per-job DB now)
            self.batch.append({
                'shard_name': self.shard_name,
                'timestamp': command.get('time', time.time()),
                'datetime_utc': datetime.utcnow().isoformat(),
                'client_address': client_address,
                'client_ip': client_ip,
                'command': cmd_name,
                'key': key[:500] if key else None,
                'key_pattern': pattern,
                'arg_shape': arg_shape,
                'command_signature': signature,
                'is_full_scan': 1 if is_full_scan else 0,
                'is_lock_op': 1 if is_lock_op else 0,
                'args_json': json.dumps(parts[1:]) if len(parts) > 1 else None,
                'raw_line': str(command)[:1000]
            })
            
            if len(self.batch) >= self.batch_size:
                self._flush_batch()
        
        except Exception as e:
            logger.debug(f"Error processing command: {e}")
    
    def _flush_batch(self):
        """Flush batch to job-specific database using bulk insert."""
        if not self.batch:
            return
        
        try:
            # Write to job-specific database
            with get_job_db_context(self.job_id) as db:
                db.bulk_insert_mappings(RedisCommand, self.batch)
            self.batch = []
        except Exception as e:
            logger.error(f"Error flushing batch to database: {e}")
            self.batch = []


def run_monitoring_job(job_id: str, password: str, profile: str = None):
    """Run a complete monitoring job in the background."""
    logger.info(f"Starting monitoring job {job_id}")
    
    # Initialize job-specific database
    logger.info(f"Initializing database for job {job_id}")
    init_job_db(job_id)
    
    with get_db_context() as db:
        job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found")
            return
        
        job.status = JobStatus.running
        job.started_at = datetime.utcnow()
        
        replication_group_id = job.replication_group_id
        region = job.region
        endpoint_type = job.endpoint_type
        duration = job.duration_seconds
    
    # Discover endpoints
    try:
        if endpoint_type == "primary":
            endpoints = get_all_endpoints(replication_group_id, region, primary_only=True, profile=profile)
        else:
            endpoints = get_replica_endpoints(replication_group_id, region, profile=profile)
        
        if not endpoints:
            with get_db_context() as db:
                job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
                if job:
                    job.status = JobStatus.failed
                    job.error_message = f"No {endpoint_type} endpoints found for {replication_group_id}"
            logger.error(f"No endpoints found for {replication_group_id}")
            return
        
        logger.info(f"Found {len(endpoints)} {endpoint_type} endpoints for {replication_group_id}:")
        for ep in endpoints:
            logger.info(f"  - {ep.get('shard', 'unknown')}: {ep.get('address')}:{ep.get('port')} ({ep.get('role', 'unknown')})")
        
    except Exception as e:
        with get_db_context() as db:
            job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
            if job:
                job.status = JobStatus.failed
                job.error_message = f"Failed to discover endpoints: {str(e)}"
        logger.error(f"Failed to discover endpoints: {e}")
        return
    
    # Create shard records in metadata DB
    shard_ids = []
    with get_db_context() as db:
        for i, endpoint in enumerate(endpoints):
            shard_id = f"{job_id}-{i}"
            shard = MonitorShard(
                id=shard_id,
                job_id=job_id,
                shard_name=endpoint['shard'],
                host=endpoint['address'],
                port=endpoint['port'],
                role=endpoint.get('role', 'replica'),
                status=ShardStatus.pending
            )
            db.add(shard)
            shard_ids.append({
                'id': shard_id,
                'host': endpoint['address'],
                'port': endpoint['port'],
                'shard_name': endpoint['shard']
            })
    
    # Start monitoring threads
    logger.info(f"Starting {len(shard_ids)} shard monitors for {duration} seconds...")
    monitors = []
    threads = []
    
    for shard_info in shard_ids:
        monitor = WebShardMonitor(
            job_id=job_id,
            shard_id=shard_info['id'],
            host=shard_info['host'],
            port=shard_info['port'],
            password=password,
            shard_name=shard_info['shard_name'],
            duration=duration
        )
        monitors.append(monitor)
        logger.info(f"  Starting monitor for {shard_info['shard_name']} on {shard_info['host']}:{shard_info['port']}")
        
        thread = Thread(target=monitor.monitor)
        thread.start()
        threads.append(thread)
    
    # Wait for all threads to complete
    logger.info(f"Waiting for {len(threads)} monitoring threads to complete (duration: {duration}s)...")
    timeout_per_thread = duration + 60
    for i, thread in enumerate(threads):
        thread.join(timeout=timeout_per_thread)
        if thread.is_alive():
            logger.warning(f"Thread {i} still running after {timeout_per_thread}s timeout")
    
    # Update job status
    total_commands = sum(m.command_count for m in monitors)
    has_errors = any(m.error for m in monitors)
    
    logger.info(f"All monitoring threads completed. Summary:")
    for m in monitors:
        logger.info(f"  - {m.shard_name}: {m.command_count} commands, error={m.error}")
    logger.info(f"Total commands: {total_commands}, has_errors: {has_errors}")
    
    # Note: Key size sampling disabled to avoid additional Redis queries
    # Key sizes can be sampled manually via the API if needed
    # if total_commands > 0:
    #     logger.info(f"Sampling key sizes for {job_id}...")
    #     try:
    #         sample_key_sizes(job_id, password, sample_limit=100)
    #     except Exception as e:
    #         logger.error(f"Failed to sample key sizes: {e}")
    
    with get_db_context() as db:
        job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
        if job:
            job.status = JobStatus.completed if not has_errors else JobStatus.completed
            job.completed_at = datetime.utcnow()
            job.total_commands = total_commands
    
    logger.info(f"Job {job_id} completed with {total_commands} total commands")


def sample_key_sizes(job_id: str, password: str, sample_limit: int = 50):
    """Sample key sizes for a completed job."""
    logger.info(f"Sampling key sizes for job {job_id}")
    
    # Get shard info from metadata DB
    with get_db_context() as db:
        shards = db.query(MonitorShard).filter(MonitorShard.job_id == job_id).all()
        shard_map = {s.shard_name: (s.host, s.port) for s in shards}
    
    # Get unique keys from job-specific DB
    with get_job_db_context(job_id) as db:
        keys_query = db.query(RedisCommand.key, RedisCommand.shard_name).filter(
            RedisCommand.key.isnot(None)
        ).distinct().limit(sample_limit * 10).all()
        
        if not keys_query:
            return
    
    # Sample keys from each shard
    keys_by_shard = {}
    for key, shard_name in keys_query:
        if shard_name not in keys_by_shard:
            keys_by_shard[shard_name] = []
        if len(keys_by_shard[shard_name]) < sample_limit:
            keys_by_shard[shard_name].append(key)
    
    sampled_count = 0
    for shard_name, keys in keys_by_shard.items():
        if shard_name not in shard_map:
            continue
        
        host, port = shard_map[shard_name]
        logger.info(f"Sampling {len(keys)} keys from {shard_name} ({host}:{port})")
        
        try:
            client = redis.Redis(
                host=host,
                port=port,
                password=password,
                ssl=True,
                ssl_cert_reqs=None,
                socket_connect_timeout=5
            )
            
            for key in keys[:sample_limit]:
                try:
                    size = client.memory_usage(key)
                    if size is not None:
                        # Update in job-specific DB
                        with get_job_db_context(job_id) as db:
                            db.query(RedisCommand).filter(
                                RedisCommand.key == key
                            ).update({'key_size_bytes': size})
                            
                            # Cache the size
                            cache = KeySizeCache(
                                key=key,
                                size_bytes=size
                            )
                            db.add(cache)
                        sampled_count += 1
                except Exception as e:
                    logger.debug(f"Could not get size for key {key}: {e}")
            
            client.close()
        
        except Exception as e:
            logger.error(f"Error sampling keys from {shard_name}: {e}")
    
    logger.info(f"Sampled sizes for {sampled_count} keys")
    logger.info(f"Key size sampling completed for job {job_id}")
