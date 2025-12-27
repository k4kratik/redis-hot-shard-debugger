"""FastAPI main application for Redis Hot Shard Debugger."""

import logging
import sys
import uuid
import json
from datetime import datetime
from typing import Optional, List

from fastapi import FastAPI, Request, Depends, Form, BackgroundTasks, Query
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
from sqlalchemy import func, desc, text
from pathlib import Path

from .db import init_db, get_db, get_job_db_context, delete_job_db, job_db_exists, get_job_db_path
from .models import MonitorJob, MonitorShard, RedisCommand, KeySizeCache, JobStatus, ShardStatus
from .runner import run_monitoring_job, sample_key_sizes

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger("redis-monitor-web")

# Initialize FastAPI app
app = FastAPI(
    title="Redis Hot Shard Debugger",
    description="Debug uneven key distribution and hot shards in ElastiCache Redis clusters",
    version="1.0.0"
)

# Setup templates
BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


# Custom Jinja2 filters
def format_bytes(value, precision=2):
    """Format bytes to human-readable format."""
    if value is None or value == 0:
        return "0 B"
    try:
        value = float(value)
    except (ValueError, TypeError):
        return str(value)
    
    units = ['B', 'KB', 'MB', 'GB', 'TB']
    unit_index = 0
    while abs(value) >= 1024 and unit_index < len(units) - 1:
        value /= 1024
        unit_index += 1
    return f"{value:.{precision}f} {units[unit_index]}"


def format_number(value, precision=1):
    """Format large numbers with K, M, B suffixes."""
    if value is None:
        return "0"
    try:
        value = float(value)
    except (ValueError, TypeError):
        return str(value)
    
    if abs(value) < 1000:
        return f"{int(value)}" if value == int(value) else f"{value:.{precision}f}"
    
    units = ['', 'K', 'M', 'B', 'T']
    unit_index = 0
    while abs(value) >= 1000 and unit_index < len(units) - 1:
        value /= 1000
        unit_index += 1
    return f"{value:.{precision}f}{units[unit_index]}"


def format_duration(seconds):
    """Format seconds to human-readable duration."""
    if seconds is None:
        return "N/A"
    try:
        seconds = int(seconds)
    except (ValueError, TypeError):
        return str(seconds)
    
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}m {secs}s"
    else:
        hours = seconds // 3600
        mins = (seconds % 3600) // 60
        return f"{hours}h {mins}m"


# Register filters
templates.env.filters["format_bytes"] = format_bytes
templates.env.filters["format_number"] = format_number
templates.env.filters["format_duration"] = format_duration


# Mount static files
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
(STATIC_DIR / "css").mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    logger.info("Starting Redis Hot Shard Debugger Web UI...")
    init_db()
    logger.info("Database initialized")
    logger.info("Web UI ready")


# =============================================================================
# HOME PAGE
# =============================================================================

@app.get("/", response_class=HTMLResponse)
async def index(request: Request, db: Session = Depends(get_db)):
    """Home page - create new monitoring job."""
    # Get recent jobs for quick reference
    recent_jobs = db.query(MonitorJob).order_by(desc(MonitorJob.created_at)).limit(5).all()
    
    # Get distinct replication group IDs for autocomplete
    prev_replication_groups = db.query(MonitorJob.replication_group_id).distinct().order_by(
        desc(MonitorJob.created_at)
    ).limit(20).all()
    prev_replication_groups = [r[0] for r in prev_replication_groups]
    
    # Get distinct job names for autocomplete
    prev_job_names = db.query(MonitorJob.name).filter(
        MonitorJob.name.isnot(None),
        MonitorJob.name != ''
    ).distinct().order_by(desc(MonitorJob.created_at)).limit(20).all()
    prev_job_names = [r[0] for r in prev_job_names]
    
    return templates.TemplateResponse("index.html", {
        "request": request,
        "page_title": "Redis Hot Shard Debugger",
        "recent_jobs": recent_jobs,
        "prev_replication_groups": prev_replication_groups,
        "prev_job_names": prev_job_names
    })


# =============================================================================
# JOB CREATION
# =============================================================================

@app.post("/jobs/create")
async def create_job(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Create and start a new monitoring job."""
    form = await request.form()
    
    replication_group_id = form.get("replication_group_id", "").strip()
    password = form.get("password", "").strip()
    endpoint_type = form.get("endpoint_type", "replica")
    duration = int(form.get("duration", 60))
    region = form.get("region", "ap-south-1").strip()
    job_name = form.get("job_name", "").strip() or None
    
    # Validation
    if not replication_group_id:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "page_title": "Redis Hot Shard Debugger",
            "error": "Replication Group ID is required",
            "recent_jobs": db.query(MonitorJob).order_by(desc(MonitorJob.created_at)).limit(5).all()
        })
    
    if not password:
        return templates.TemplateResponse("index.html", {
            "request": request,
            "page_title": "Redis Hot Shard Debugger",
            "error": "Redis password is required",
            "recent_jobs": db.query(MonitorJob).order_by(desc(MonitorJob.created_at)).limit(5).all()
        })
    
    # Create job
    job_id = str(uuid.uuid4())
    job = MonitorJob(
        id=job_id,
        name=job_name,
        replication_group_id=replication_group_id,
        region=region,
        endpoint_type=endpoint_type,
        duration_seconds=duration,
        status=JobStatus.pending,
        config_json=json.dumps({
            "region": region,
            "endpoint_type": endpoint_type,
            "duration": duration
        })
    )
    db.add(job)
    db.commit()
    
    logger.info(f"Created job {job_id} for {replication_group_id}")
    
    # Start background monitoring task
    # Note: Password is passed directly (not stored in DB for security)
    background_tasks.add_task(run_monitoring_job, job_id, password)
    
    return RedirectResponse(url=f"/jobs/{job_id}", status_code=303)


# =============================================================================
# JOBS LIST
# =============================================================================

@app.get("/jobs", response_class=HTMLResponse)
async def list_jobs(request: Request, db: Session = Depends(get_db)):
    """List all monitoring jobs."""
    jobs = db.query(MonitorJob).order_by(desc(MonitorJob.created_at)).all()
    
    jobs_data = []
    for job in jobs:
        shard_count = len(job.shards)
        completed_count = sum(1 for s in job.shards if s.status == ShardStatus.completed)
        failed_count = sum(1 for s in job.shards if s.status == ShardStatus.failed)
        
        jobs_data.append({
            "job": job,
            "shard_count": shard_count,
            "completed_count": completed_count,
            "failed_count": failed_count
        })
    
    return templates.TemplateResponse("jobs.html", {
        "request": request,
        "page_title": "Jobs",
        "jobs": jobs_data
    })


# =============================================================================
# JOB DETAIL
# =============================================================================

@app.get("/jobs/{job_id}", response_class=HTMLResponse)
async def job_detail(request: Request, job_id: str, db: Session = Depends(get_db)):
    """Job detail page with shard status - loads instantly, heavy data fetched async."""
    job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
    
    if not job:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Job not found",
            "page_title": "Error"
        }, status_code=404)
    
    # Get shard stats (lightweight - from metadata DB only)
    shards_data = []
    for shard in job.shards:
        shards_data.append({
            "shard": shard,
            "command_count": shard.command_count,
            "qps": shard.qps
        })
    
    # Sort by command count descending to highlight hot shards
    shards_data.sort(key=lambda x: x['command_count'], reverse=True)
    
    # Return page immediately - chart data will be loaded async via API
    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "job": job,
        "shards": shards_data,
        "page_title": f"Job: {job.name or job.id[:8]}"
    })


# =============================================================================
# ANALYSIS PAGE - Advanced Query & Visualization
# =============================================================================

@app.get("/jobs/{job_id}/analysis", response_class=HTMLResponse)
async def job_analysis(
    request: Request,
    job_id: str,
    group_by: str = "key_pattern",
    shard_filter: Optional[str] = None,
    command_filter: Optional[str] = None,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """Advanced analysis page with grouping and key pattern analysis."""
    job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
    
    if not job:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Job not found",
            "page_title": "Error"
        }, status_code=404)
    
    # Get available shards for filter dropdown (from metadata DB)
    shards = db.query(MonitorShard).filter(MonitorShard.job_id == job_id).all()
    
    # Initialize defaults
    commands = []
    analysis_data = []
    total_commands = 0
    unique_keys = 0
    unique_patterns = 0
    
    # Query from job-specific database if it exists
    if job_db_exists(job_id):
        with get_job_db_context(job_id) as job_db:
            # Build base filter (no job_id needed - per-job DB)
            base_filter = []
            
            if shard_filter:
                base_filter.append(RedisCommand.shard_name == shard_filter)
            
            if command_filter:
                base_filter.append(RedisCommand.command == command_filter.upper())
            
            # Get available commands for filter dropdown
            commands_raw = job_db.query(RedisCommand.command).distinct().all()
            commands = sorted([c[0] for c in commands_raw if c[0]])
            
            # Group by analysis
            if group_by == "key_pattern":
                query = job_db.query(
                    RedisCommand.key_pattern,
                    func.count(RedisCommand.id).label('count'),
                    func.avg(RedisCommand.key_size_bytes).label('avg_size'),
                    func.sum(RedisCommand.key_size_bytes).label('total_size')
                )
                if base_filter:
                    query = query.filter(*base_filter)
                results = query.filter(
                    RedisCommand.key_pattern.isnot(None)
                ).group_by(
                    RedisCommand.key_pattern
                ).order_by(
                    desc('count')
                ).limit(limit).all()
                
                analysis_data = [{
                    'name': r[0],
                    'count': r[1],
                    'avg_size': r[2],
                    'total_size': r[3]
                } for r in results]
            
            elif group_by == "shard":
                query = job_db.query(
                    RedisCommand.shard_name,
                    func.count(RedisCommand.id).label('count'),
                    func.sum(RedisCommand.key_size_bytes).label('total_size')
                )
                if base_filter:
                    query = query.filter(*base_filter)
                results = query.group_by(
                    RedisCommand.shard_name
                ).order_by(
                    desc('count')
                ).limit(limit).all()
                
                analysis_data = [{
                    'name': r[0],
                    'count': r[1],
                    'total_size': r[2]
                } for r in results]
            
            elif group_by == "command":
                query = job_db.query(
                    RedisCommand.command,
                    func.count(RedisCommand.id).label('count')
                )
                if base_filter:
                    query = query.filter(*base_filter)
                results = query.group_by(
                    RedisCommand.command
                ).order_by(
                    desc('count')
                ).limit(limit).all()
                
                analysis_data = [{
                    'name': r[0],
                    'count': r[1]
                } for r in results]
            
            elif group_by == "client_ip":
                query = job_db.query(
                    RedisCommand.client_ip,
                    func.count(RedisCommand.id).label('count')
                )
                if base_filter:
                    query = query.filter(*base_filter)
                results = query.filter(
                    RedisCommand.client_ip.isnot(None)
                ).group_by(
                    RedisCommand.client_ip
                ).order_by(
                    desc('count')
                ).limit(limit).all()
                
                analysis_data = [{
                    'name': r[0],
                    'count': r[1]
                } for r in results]
            
            elif group_by == "key":
                query = job_db.query(
                    RedisCommand.key,
                    RedisCommand.shard_name,
                    func.count(RedisCommand.id).label('count'),
                    func.max(RedisCommand.key_size_bytes).label('size')
                )
                if base_filter:
                    query = query.filter(*base_filter)
                results = query.filter(
                    RedisCommand.key.isnot(None)
                ).group_by(
                    RedisCommand.key,
                    RedisCommand.shard_name
                ).order_by(
                    desc('count')
                ).limit(limit).all()
                
                analysis_data = [{
                    'name': r[0],
                    'shard': r[1],
                    'count': r[2],
                    'size': r[3]
                } for r in results]
            
            # Get overall stats
            total_commands = job_db.query(func.count(RedisCommand.id)).scalar() or 0
            unique_keys = job_db.query(func.count(func.distinct(RedisCommand.key))).scalar() or 0
            unique_patterns = job_db.query(func.count(func.distinct(RedisCommand.key_pattern))).scalar() or 0
    
    return templates.TemplateResponse("analysis.html", {
        "request": request,
        "job": job,
        "shards": shards,
        "commands": commands,
        "group_by": group_by,
        "shard_filter": shard_filter,
        "command_filter": command_filter,
        "limit": limit,
        "analysis_data": analysis_data,
        "total_commands": total_commands,
        "unique_keys": unique_keys,
        "unique_patterns": unique_patterns,
        "page_title": f"Analysis: {job.name or job.id[:8]}"
    })


# =============================================================================
# SHARD DETAIL
# =============================================================================

@app.get("/jobs/{job_id}/shards/{shard_name}", response_class=HTMLResponse)
async def shard_detail(
    request: Request,
    job_id: str,
    shard_name: str,
    tab: str = "overview",
    db: Session = Depends(get_db)
):
    """Shard detail page with commands and analysis."""
    job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
    shard = db.query(MonitorShard).filter(
        MonitorShard.job_id == job_id,
        MonitorShard.shard_name == shard_name
    ).first()
    
    if not job or not shard:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Job or shard not found",
            "page_title": "Error"
        }, status_code=404)
    
    # Initialize defaults
    command_dist = []
    top_patterns = []
    top_keys = []
    recent_commands = []
    
    # Query from job-specific database
    if job_db_exists(job_id):
        with get_job_db_context(job_id) as job_db:
            # Get command distribution
            command_dist = job_db.query(
                RedisCommand.command,
                func.count(RedisCommand.id).label('count')
            ).filter(
                RedisCommand.shard_name == shard_name
            ).group_by(
                RedisCommand.command
            ).order_by(
                desc('count')
            ).limit(10).all()
            
            # Get top key patterns
            top_patterns = job_db.query(
                RedisCommand.key_pattern,
                func.count(RedisCommand.id).label('count'),
                func.avg(RedisCommand.key_size_bytes).label('avg_size')
            ).filter(
                RedisCommand.shard_name == shard_name,
                RedisCommand.key_pattern.isnot(None)
            ).group_by(
                RedisCommand.key_pattern
            ).order_by(
                desc('count')
            ).limit(20).all()
            
            # Get top individual keys
            top_keys = job_db.query(
                RedisCommand.key,
                func.count(RedisCommand.id).label('count'),
                func.max(RedisCommand.key_size_bytes).label('size')
            ).filter(
                RedisCommand.shard_name == shard_name,
                RedisCommand.key.isnot(None)
            ).group_by(
                RedisCommand.key
            ).order_by(
                desc('count')
            ).limit(30).all()
            
            # Get recent commands - convert to dicts to avoid DetachedInstanceError
            recent_cmd_rows = job_db.query(RedisCommand).filter(
                RedisCommand.shard_name == shard_name
            ).order_by(
                desc(RedisCommand.timestamp)
            ).limit(100).all()
            
            recent_commands = [{
                'datetime_utc': cmd.datetime_utc,
                'command': cmd.command,
                'key': cmd.key,
                'client_ip': cmd.client_ip,
                'args_json': cmd.args_json
            } for cmd in recent_cmd_rows]
    
    return templates.TemplateResponse("shard_detail.html", {
        "request": request,
        "job": job,
        "shard": shard,
        "tab": tab,
        "command_dist": command_dist,
        "top_patterns": top_patterns,
        "top_keys": top_keys,
        "recent_commands": recent_commands,
        "page_title": f"Shard: {shard_name}"
    })


# =============================================================================
# API ENDPOINTS
# =============================================================================

@app.get("/api/jobs/{job_id}/status")
async def get_job_status(job_id: str, db: Session = Depends(get_db)):
    """Get current job status for polling."""
    job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
    
    if not job:
        return {"error": "Job not found"}
    
    shards_status = []
    for shard in job.shards:
        shards_status.append({
            "shard_name": shard.shard_name,
            "host": shard.host,
            "port": shard.port,
            "status": shard.status.value,
            "command_count": shard.command_count,
            "qps": shard.qps,
            "error": shard.error_message
        })
    
    # Calculate actual commands from job-specific database for accuracy
    actual_total = 0
    if job_db_exists(job_id):
        try:
            with get_job_db_context(job_id) as job_db:
                actual_total = job_db.query(func.count(RedisCommand.id)).scalar() or 0
        except:
            pass
    
    return {
        "job_id": job_id,
        "status": job.status.value,
        "total_commands": max(job.total_commands, actual_total),
        "error_message": job.error_message,
        "started_at": job.started_at.isoformat() + 'Z' if job.started_at else None,
        "shards": shards_status
    }


@app.get("/api/jobs/{job_id}/chart-data")
async def get_chart_data(
    job_id: str,
    chart_type: str = "shard_distribution",
    db: Session = Depends(get_db)
):
    """Get chart data for visualizations."""
    if not job_db_exists(job_id):
        return {"labels": [], "values": []}
    
    with get_job_db_context(job_id) as job_db:
        if chart_type == "shard_distribution":
            results = job_db.query(
                RedisCommand.shard_name,
                func.count(RedisCommand.id).label('count')
            ).group_by(
                RedisCommand.shard_name
            ).all()
            
            return {
                "labels": [r[0] for r in results],
                "values": [r[1] for r in results]
            }
        
        elif chart_type == "command_distribution":
            results = job_db.query(
                RedisCommand.command,
                func.count(RedisCommand.id).label('count')
            ).group_by(
                RedisCommand.command
            ).order_by(
                desc('count')
            ).limit(10).all()
            
            return {
                "labels": [r[0] for r in results],
                "values": [r[1] for r in results]
            }
        
        elif chart_type == "key_pattern_distribution":
            results = job_db.query(
                RedisCommand.key_pattern,
                func.count(RedisCommand.id).label('count')
            ).filter(
                RedisCommand.key_pattern.isnot(None)
            ).group_by(
                RedisCommand.key_pattern
            ).order_by(
                desc('count')
            ).limit(10).all()
            
            return {
                "labels": [r[0] for r in results],
                "values": [r[1] for r in results]
            }
    
    return {"labels": [], "values": []}


@app.get("/api/jobs/{job_id}/stats")
async def get_job_stats(job_id: str, db: Session = Depends(get_db)):
    """Get all statistics for job detail page - loaded async for fast page load."""
    job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
    
    if not job or job.status.value != 'completed' or not job_db_exists(job_id):
        return {
            "loaded": False,
            "command_types": [],
            "command_by_shard": {},
            "top_patterns": [],
            "pattern_by_shard": {}
        }
    
    command_by_shard = {}
    pattern_by_shard = {}
    cmd_types = []
    top_patterns = []
    
    with get_job_db_context(job_id) as job_db:
        # Get all command types used
        cmd_types_raw = job_db.query(RedisCommand.command).distinct().all()
        cmd_types = sorted([c[0] for c in cmd_types_raw if c[0]])
        
        # Get command counts per shard
        shard_cmd_data = job_db.query(
            RedisCommand.shard_name,
            RedisCommand.command,
            func.count(RedisCommand.id).label('count')
        ).group_by(
            RedisCommand.shard_name,
            RedisCommand.command
        ).all()
        
        # Organize data: {shard_name: {command: count}}
        for row in shard_cmd_data:
            shard_name, cmd, count = row
            if shard_name not in command_by_shard:
                command_by_shard[shard_name] = {}
            command_by_shard[shard_name][cmd] = count
        
        # Get top 10 key patterns overall
        top_patterns_raw = job_db.query(
            RedisCommand.key_pattern,
            func.count(RedisCommand.id).label('count')
        ).filter(
            RedisCommand.key_pattern.isnot(None)
        ).group_by(
            RedisCommand.key_pattern
        ).order_by(
            func.count(RedisCommand.id).desc()
        ).limit(10).all()
        top_patterns = [p[0] for p in top_patterns_raw if p[0]]
        
        # Get pattern counts per shard (for top patterns only)
        if top_patterns:
            shard_pattern_data = job_db.query(
                RedisCommand.shard_name,
                RedisCommand.key_pattern,
                func.count(RedisCommand.id).label('count')
            ).filter(
                RedisCommand.key_pattern.in_(top_patterns)
            ).group_by(
                RedisCommand.shard_name,
                RedisCommand.key_pattern
            ).all()
            
            # Organize: {shard_name: {pattern: count}}
            for row in shard_pattern_data:
                shard_name, pattern, count = row
                if shard_name not in pattern_by_shard:
                    pattern_by_shard[shard_name] = {}
                pattern_by_shard[shard_name][pattern] = count
    
    return {
        "loaded": True,
        "command_types": cmd_types,
        "command_by_shard": command_by_shard,
        "top_patterns": top_patterns,
        "pattern_by_shard": pattern_by_shard
    }


@app.post("/api/jobs/{job_id}/sample-sizes")
async def trigger_size_sampling(
    job_id: str,
    password: str = Form(...),
    background_tasks: BackgroundTasks = BackgroundTasks(),
    db: Session = Depends(get_db)
):
    """Trigger key size sampling for a job."""
    job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
    
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    
    background_tasks.add_task(sample_key_sizes, job_id, password)
    
    return {"status": "sampling started"}


@app.delete("/api/jobs/{job_id}")
async def delete_job(job_id: str, db: Session = Depends(get_db)):
    """Delete a job and all its data."""
    job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
    
    if not job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    
    # Delete job-specific database file (contains all commands)
    delete_job_db(job_id)
    
    # Delete metadata (shards and job record)
    db.query(MonitorShard).filter(MonitorShard.job_id == job_id).delete()
    db.delete(job)
    db.commit()
    
    return {"status": "deleted"}


# =============================================================================
# RE-RUN JOB
# =============================================================================

@app.post("/jobs/{job_id}/rerun")
async def rerun_job(
    job_id: str,
    background_tasks: BackgroundTasks,
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    """Re-run a job with the same configuration but new password."""
    original_job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
    
    if not original_job:
        return JSONResponse({"error": "Job not found"}, status_code=404)
    
    # Create new job with same config
    new_job_id = str(uuid.uuid4())
    new_job = MonitorJob(
        id=new_job_id,
        name=f"{original_job.name or original_job.replication_group_id} (re-run)" if original_job.name else None,
        replication_group_id=original_job.replication_group_id,
        region=original_job.region,
        endpoint_type=original_job.endpoint_type,
        duration_seconds=original_job.duration_seconds,
        status=JobStatus.pending,
        config_json=original_job.config_json
    )
    db.add(new_job)
    db.commit()
    
    logger.info(f"Created re-run job {new_job_id} from {job_id}")
    
    # Start background monitoring
    background_tasks.add_task(run_monitoring_job, new_job_id, password)
    
    return RedirectResponse(url=f"/jobs/{new_job_id}", status_code=303)


# =============================================================================
# COMPARE JOBS
# =============================================================================

@app.get("/compare", response_class=HTMLResponse)
async def compare_jobs(
    request: Request,
    jobs: str = Query(default=""),
    db: Session = Depends(get_db)
):
    """Compare multiple monitoring jobs side by side."""
    job_ids = [j.strip() for j in jobs.split(",") if j.strip()]
    
    # Get all completed jobs for the selection UI
    all_completed_jobs = db.query(MonitorJob).filter(
        MonitorJob.status == JobStatus.completed
    ).order_by(desc(MonitorJob.created_at)).limit(20).all()
    
    if len(job_ids) < 2:
        return templates.TemplateResponse("compare.html", {
            "request": request,
            "jobs": [],
            "all_jobs": all_completed_jobs,
            "stats": {},
            "page_title": "Compare Jobs"
        })
    
    # Fetch job objects
    job_objects = []
    for job_id in job_ids[:4]:  # Max 4 jobs
        job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
        if job and job.status == JobStatus.completed:
            job_objects.append(job)
    
    if len(job_objects) < 2:
        return templates.TemplateResponse("compare.html", {
            "request": request,
            "jobs": [],
            "all_jobs": all_completed_jobs,
            "stats": {},
            "page_title": "Compare Jobs"
        })
    
    # Gather stats for each job
    stats = {}
    for job in job_objects:
        job_stats = {
            "shard_count": 0,
            "unique_keys": 0,
            "unique_patterns": 0,
            "top_commands": [],
            "top_patterns": [],
            "shard_distribution": []
        }
        
        # Shard count from main DB
        job_stats["shard_count"] = db.query(MonitorShard).filter(
            MonitorShard.job_id == job.id
        ).count()
        
        # Query job-specific DB for detailed stats
        if job_db_exists(job.id):
            with get_job_db_context(job.id) as job_db:
                # Unique keys
                unique_keys_result = job_db.query(
                    func.count(func.distinct(RedisCommand.key))
                ).filter(RedisCommand.key.isnot(None)).scalar()
                job_stats["unique_keys"] = unique_keys_result or 0
                
                # Unique patterns
                unique_patterns_result = job_db.query(
                    func.count(func.distinct(RedisCommand.key_pattern))
                ).filter(RedisCommand.key_pattern.isnot(None)).scalar()
                job_stats["unique_patterns"] = unique_patterns_result or 0
                
                # Top commands
                top_cmds = job_db.query(
                    RedisCommand.command,
                    func.count(RedisCommand.id).label('count')
                ).group_by(
                    RedisCommand.command
                ).order_by(
                    func.count(RedisCommand.id).desc()
                ).limit(10).all()
                job_stats["top_commands"] = [{"command": c, "count": cnt} for c, cnt in top_cmds]
                
                # Top patterns
                top_pats = job_db.query(
                    RedisCommand.key_pattern,
                    func.count(RedisCommand.id).label('count')
                ).filter(
                    RedisCommand.key_pattern.isnot(None)
                ).group_by(
                    RedisCommand.key_pattern
                ).order_by(
                    func.count(RedisCommand.id).desc()
                ).limit(10).all()
                job_stats["top_patterns"] = [{"pattern": p, "count": cnt} for p, cnt in top_pats]
                
                # Shard distribution
                shard_dist = job_db.query(
                    RedisCommand.shard_name,
                    func.count(RedisCommand.id).label('count')
                ).group_by(
                    RedisCommand.shard_name
                ).order_by(
                    RedisCommand.shard_name
                ).all()
                job_stats["shard_distribution"] = [{"shard_name": s, "count": cnt} for s, cnt in shard_dist]
        
        stats[job.id] = job_stats
    
    return templates.TemplateResponse("compare.html", {
        "request": request,
        "jobs": job_objects,
        "stats": stats,
        "page_title": "Compare Jobs"
    })


# =============================================================================
# CUSTOM SQL QUERY
# =============================================================================

@app.get("/query", response_class=HTMLResponse)
async def query_page(
    request: Request,
    sql: Optional[str] = None,
    job_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Custom SQL query page - queries job-specific database."""
    results = None
    error = None
    columns = []
    
    # Get all jobs for dropdown
    jobs = db.query(MonitorJob).order_by(desc(MonitorJob.created_at)).all()
    
    if sql and job_id:
        try:
            # Safety: only allow SELECT queries
            if not sql.strip().upper().startswith("SELECT"):
                error = "Only SELECT queries are allowed"
            elif not job_db_exists(job_id):
                error = f"No data found for job {job_id}. The job may not have captured any commands."
            else:
                # Query the job-specific database
                with get_job_db_context(job_id) as job_db:
                    result = job_db.execute(text(sql))
                    columns = list(result.keys())
                    results = [dict(row._mapping) for row in result.fetchall()]
        except Exception as e:
            error = str(e)
    elif sql and not job_id:
        error = "Please select a job to query"
    
    return templates.TemplateResponse("query.html", {
        "request": request,
        "sql": sql or "",
        "results": results,
        "columns": columns,
        "error": error,
        "jobs": jobs,
        "selected_job_id": job_id,
        "page_title": "SQL Query"
    })

