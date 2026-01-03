"""Database connection and session management for web UI.

Architecture:
- Main DB (redis_monitor.db): Job metadata only (MonitorJob, MonitorShard)
- Per-job DB (data/jobs/{job_id}.db): Commands for each job (RedisCommand, KeySizeCache)
"""

from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator
import os
import logging

from .models import MetadataBase, CommandBase

logger = logging.getLogger("redis-monitor-web")

# ============================================================================
# PATHS
# ============================================================================

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent

# Main metadata database
METADATA_DB_PATH = PROJECT_ROOT / "redis_monitor.db"
METADATA_DATABASE_URL = f"sqlite:///{METADATA_DB_PATH}"

# Per-job databases directory
JOBS_DATA_DIR = PROJECT_ROOT / "data" / "jobs"


def get_job_db_path(job_id: str) -> Path:
    """Get path to job-specific database file."""
    return JOBS_DATA_DIR / f"{job_id}.db"


def get_job_db_url(job_id: str) -> str:
    """Get SQLite URL for job-specific database."""
    return f"sqlite:///{get_job_db_path(job_id)}"


# ============================================================================
# METADATA DATABASE (jobs, shards)
# ============================================================================

# Create engine for metadata DB
metadata_engine = create_engine(
    METADATA_DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False
)

# Session factory for metadata
MetadataSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=metadata_engine)


def _migrate_metadata_db_schema() -> None:
    """Add any missing columns to the metadata database.
    
    This handles schema migrations for databases created before new columns were added.
    Called automatically at module load time to ensure columns exist before any queries.
    """
    new_columns_shards = [
        # Redis server info
        ("redis_version", "TEXT"),
        # Memory info
        ("memory_used_bytes", "INTEGER"),
        ("memory_max_bytes", "INTEGER"),
        ("memory_peak_bytes", "INTEGER"),
        ("memory_rss_bytes", "INTEGER"),
        # CPU info
        ("cpu_sys_start", "REAL"),
        ("cpu_user_start", "REAL"),
        ("cpu_sys_end", "REAL"),
        ("cpu_user_end", "REAL"),
        ("cpu_sys_delta", "REAL"),
        ("cpu_user_delta", "REAL"),
    ]
    
    try:
        with metadata_engine.connect() as conn:
            # Check if table exists
            result = conn.execute(text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='monitor_shards'"
            ))
            if not result.fetchone():
                return  # Table doesn't exist yet
            
            # Get existing columns
            result = conn.execute(text("PRAGMA table_info(monitor_shards)"))
            existing_columns = {row[1] for row in result.fetchall()}
            
            # Add missing columns
            for col_name, col_def in new_columns_shards:
                if col_name not in existing_columns:
                    try:
                        conn.execute(text(f"ALTER TABLE monitor_shards ADD COLUMN {col_name} {col_def}"))
                        logger.info(f"Added column {col_name} to monitor_shards table")
                    except Exception as e:
                        logger.debug(f"Could not add column {col_name}: {e}")
            
            conn.commit()
    except Exception as e:
        logger.debug(f"Could not migrate metadata schema: {e}")


# Run migration immediately at module load time
# This ensures columns exist before any ORM queries
_migrate_metadata_db_schema()


def init_metadata_db() -> None:
    """Initialize metadata database and create tables."""
    MetadataBase.metadata.create_all(bind=metadata_engine)
    # Migration already ran at module load, but run again to be safe
    _migrate_metadata_db_schema()


def get_db() -> Generator[Session, None, None]:
    """Dependency for getting metadata database session."""
    db = MetadataSessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def get_db_context() -> Generator[Session, None, None]:
    """Context manager for metadata database session (for background tasks)."""
    db = MetadataSessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


# ============================================================================
# JOB-SPECIFIC DATABASES (commands)
# ============================================================================

# Cache of job engines to avoid recreating them
_job_engines = {}
_job_sessions = {}


def get_job_engine(job_id: str):
    """Get or create SQLAlchemy engine for a job's database."""
    if job_id not in _job_engines:
        # Ensure directory exists
        JOBS_DATA_DIR.mkdir(parents=True, exist_ok=True)
        
        # Check if DB already exists (for migration)
        db_existed = get_job_db_path(job_id).exists()
        
        db_url = get_job_db_url(job_id)
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            echo=False
        )
        _job_engines[job_id] = engine
        
        # Run migration on existing databases to add new columns
        if db_existed:
            _migrate_job_db_schema(engine, job_id)
    
    return _job_engines[job_id]


def _migrate_job_db_schema(engine, job_id: str) -> None:
    """Add any missing columns to an existing job database.
    
    This handles schema migrations for databases created before new columns were added.
    SQLite supports ALTER TABLE ... ADD COLUMN for adding new nullable columns.
    
    Note: This is called internally by get_job_engine, not directly.
    """
    # Define columns that may be missing in older databases
    # Format: (column_name, column_definition)
    new_columns = [
        ("arg_shape", "TEXT"),
        ("command_signature", "TEXT"),
        ("is_full_scan", "INTEGER DEFAULT 0"),
        ("is_lock_op", "INTEGER DEFAULT 0"),
    ]
    
    with engine.connect() as conn:
        # Check if table exists first
        result = conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='redis_commands'"
        ))
        if not result.fetchone():
            return  # Table doesn't exist yet, nothing to migrate
        
        # Get existing columns
        result = conn.execute(text("PRAGMA table_info(redis_commands)"))
        existing_columns = {row[1] for row in result.fetchall()}
        
        # Add missing columns
        for col_name, col_def in new_columns:
            if col_name not in existing_columns:
                try:
                    conn.execute(text(f"ALTER TABLE redis_commands ADD COLUMN {col_name} {col_def}"))
                    logger.info(f"Added column {col_name} to job {job_id} database")
                except Exception as e:
                    # Column might already exist (race condition) or other issue
                    logger.debug(f"Could not add column {col_name}: {e}")
        
        conn.commit()


def init_job_db(job_id: str) -> None:
    """Initialize a job-specific database and create tables."""
    engine = get_job_engine(job_id)
    CommandBase.metadata.create_all(bind=engine)


def get_job_session_factory(job_id: str):
    """Get session factory for a job's database."""
    if job_id not in _job_sessions:
        engine = get_job_engine(job_id)
        _job_sessions[job_id] = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return _job_sessions[job_id]


@contextmanager
def get_job_db_context(job_id: str) -> Generator[Session, None, None]:
    """Context manager for job-specific database session."""
    SessionLocal = get_job_session_factory(job_id)
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_job_db(job_id: str) -> bool:
    """Delete a job's database file and cleanup cached connections."""
    # Close and remove cached engine/session
    if job_id in _job_engines:
        _job_engines[job_id].dispose()
        del _job_engines[job_id]
    if job_id in _job_sessions:
        del _job_sessions[job_id]
    
    # Delete the file
    db_path = get_job_db_path(job_id)
    if db_path.exists():
        os.remove(db_path)
        return True
    return False


def job_db_exists(job_id: str) -> bool:
    """Check if a job's database file exists."""
    return get_job_db_path(job_id).exists()


# ============================================================================
# INITIALIZATION
# ============================================================================

def init_db() -> None:
    """Initialize all databases (just metadata on startup)."""
    JOBS_DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_metadata_db()
