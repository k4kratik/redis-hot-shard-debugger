"""SQLAlchemy models for Redis Monitor Web UI.

Architecture:
- MetadataBase: Models stored in main DB (redis_monitor.db)
- CommandBase: Models stored in per-job DB (data/jobs/{job_id}.db)
"""

from datetime import datetime
from sqlalchemy import Column, String, DateTime, Integer, Float, Text, ForeignKey, Enum as SQLEnum, Index
from sqlalchemy.orm import relationship, declarative_base
import enum

# Separate bases for different databases
MetadataBase = declarative_base()
CommandBase = declarative_base()

# Keep Base as alias for backward compatibility during migration
Base = MetadataBase


class JobStatus(enum.Enum):
    """Job execution status."""
    pending = "pending"
    running = "running"
    finalizing = "finalizing"
    completed = "completed"
    failed = "failed"
    cancelled = "cancelled"


class ShardStatus(enum.Enum):
    """Per-shard monitoring status."""
    pending = "pending"
    connecting = "connecting"
    monitoring = "monitoring"
    finalizing = "finalizing"
    completed = "completed"
    failed = "failed"


# ============================================================================
# METADATA MODELS (stored in redis_monitor.db)
# ============================================================================

class MonitorJob(MetadataBase):
    """Monitoring job metadata."""
    __tablename__ = "monitor_jobs"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=True)
    replication_group_id = Column(String, nullable=False)
    region = Column(String, default="ap-south-1")
    endpoint_type = Column(String, default="replica")
    duration_seconds = Column(Integer, default=60)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    status = Column(SQLEnum(JobStatus), default=JobStatus.pending, nullable=False)
    
    error_message = Column(Text, nullable=True)
    total_commands = Column(Integer, default=0)
    
    config_json = Column(Text, nullable=True)
    
    # Relationship to shards
    shards = relationship("MonitorShard", back_populates="job", cascade="all, delete-orphan")


class MonitorShard(MetadataBase):
    """Per-shard monitoring status and stats."""
    __tablename__ = "monitor_shards"

    id = Column(String, primary_key=True)
    job_id = Column(String, ForeignKey("monitor_jobs.id"), nullable=False)
    shard_name = Column(String, nullable=False)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False)
    role = Column(String, default="replica")
    
    status = Column(SQLEnum(ShardStatus), default=ShardStatus.pending, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    
    error_message = Column(Text, nullable=True)
    command_count = Column(Integer, default=0)
    qps = Column(Float, default=0.0)
    
    # Redis server info (captured at start)
    redis_version = Column(String, nullable=True)  # e.g., "7.0.7"
    
    # Memory info (captured at end of monitoring)
    memory_used_bytes = Column(Integer, nullable=True)  # used_memory
    memory_max_bytes = Column(Integer, nullable=True)   # maxmemory (0 = no limit)
    memory_peak_bytes = Column(Integer, nullable=True)  # used_memory_peak
    memory_rss_bytes = Column(Integer, nullable=True)   # used_memory_rss (OS-level)
    
    # CPU metrics from INFO command (captured at start and end)
    cpu_sys_start = Column(Float, nullable=True)  # used_cpu_sys at start
    cpu_user_start = Column(Float, nullable=True)  # used_cpu_user at start
    cpu_sys_end = Column(Float, nullable=True)  # used_cpu_sys at end
    cpu_user_end = Column(Float, nullable=True)  # used_cpu_user at end
    cpu_sys_delta = Column(Float, nullable=True)  # CPU sys consumed during monitoring
    cpu_user_delta = Column(Float, nullable=True)  # CPU user consumed during monitoring
    
    # Relationship to parent job
    job = relationship("MonitorJob", back_populates="shards")


# ============================================================================
# COMMAND MODELS (stored in per-job DB: data/jobs/{job_id}.db)
# ============================================================================

class RedisCommand(CommandBase):
    """Captured Redis commands from MONITOR."""
    __tablename__ = "redis_commands"

    id = Column(Integer, primary_key=True, autoincrement=True)
    shard_name = Column(String, nullable=False, index=True)
    
    timestamp = Column(Float, nullable=False)
    datetime_utc = Column(String, nullable=False)
    
    client_address = Column(String, nullable=True)
    client_ip = Column(String, nullable=True, index=True)
    
    command = Column(String, nullable=False, index=True)
    key = Column(String, nullable=True, index=True)
    key_pattern = Column(String, nullable=True, index=True)
    key_size_bytes = Column(Integer, nullable=True)
    
    # NEW: Derived insight fields
    arg_shape = Column(String, nullable=True)  # e.g., "0 -1", "NX EX 300", "MATCH * COUNT 100"
    command_signature = Column(String, nullable=True, index=True)  # e.g., "LRANGE | user:{ID}:feed | 0 -1"
    
    # Flags for quick filtering
    is_full_scan = Column(Integer, default=0)  # 1 if KEYS *, SCAN, LRANGE 0 -1, etc.
    is_lock_op = Column(Integer, default=0)    # 1 if SETNX, SET NX, WATCH, etc.
    
    args_json = Column(Text, nullable=True)
    raw_line = Column(Text, nullable=True)
    
    # Composite indexes for faster aggregation queries
    __table_args__ = (
        Index('ix_commands_shard_cmd', 'shard_name', 'command'),
        Index('ix_commands_pattern', 'key_pattern'),
        Index('ix_commands_signature', 'command_signature'),
        Index('ix_commands_client_sig', 'client_ip', 'command_signature'),
    )


class KeySizeCache(CommandBase):
    """Cache for key sizes to avoid repeated MEMORY USAGE calls."""
    __tablename__ = "key_size_cache"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String, nullable=False, index=True)
    size_bytes = Column(Integer, nullable=True)
    sampled_at = Column(DateTime, default=datetime.utcnow)
