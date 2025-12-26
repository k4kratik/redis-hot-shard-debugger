"""Database connection and session management for web UI.

Architecture:
- Main DB (redis_monitor.db): Job metadata only (MonitorJob, MonitorShard)
- Per-job DB (data/jobs/{job_id}.db): Commands for each job (RedisCommand, KeySizeCache)
"""

from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from contextlib import contextmanager
from typing import Generator
import os

from .models import MetadataBase, CommandBase

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


def init_metadata_db() -> None:
    """Initialize metadata database and create tables."""
    MetadataBase.metadata.create_all(bind=metadata_engine)


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
        
        db_url = get_job_db_url(job_id)
        engine = create_engine(
            db_url,
            connect_args={"check_same_thread": False},
            echo=False
        )
        _job_engines[job_id] = engine
    return _job_engines[job_id]


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
