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

from .db import init_db, get_db
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
    """Job detail page with shard status."""
    job = db.query(MonitorJob).filter(MonitorJob.id == job_id).first()
    
    if not job:
        return templates.TemplateResponse("error.html", {
            "request": request,
            "error": "Job not found",
            "page_title": "Error"
        }, status_code=404)
    
    # Get shard stats
    shards_data = []
    for shard in job.shards:
        shards_data.append({
            "shard": shard,
            "command_count": shard.command_count,
            "qps": shard.qps
        })
    
    # Sort by command count descending to highlight hot shards
    shards_data.sort(key=lambda x: x['command_count'], reverse=True)
    
    # Get command distribution per shard (for completed jobs)
    command_by_shard = {}
    pattern_by_shard = {}
    cmd_types = []
    top_patterns = []
    
    if job.status.value == 'completed':
        from sqlalchemy import func
        
        # Get all command types used
        cmd_types_raw = db.query(RedisCommand.command).filter(
            RedisCommand.job_id == job_id
        ).distinct().all()
        cmd_types = sorted([c[0] for c in cmd_types_raw if c[0]])
        
        # Get command counts per shard
        shard_cmd_data = db.query(
            RedisCommand.shard_name,
            RedisCommand.command,
            func.count(RedisCommand.id).label('count')
        ).filter(
            RedisCommand.job_id == job_id
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
        top_patterns_raw = db.query(
            RedisCommand.key_pattern,
            func.count(RedisCommand.id).label('count')
        ).filter(
            RedisCommand.job_id == job_id,
            RedisCommand.key_pattern.isnot(None)
        ).group_by(
            RedisCommand.key_pattern
        ).order_by(
            func.count(RedisCommand.id).desc()
        ).limit(10).all()
        top_patterns = [p[0] for p in top_patterns_raw if p[0]]
        
        # Get pattern counts per shard (for top patterns only)
        if top_patterns:
            shard_pattern_data = db.query(
                RedisCommand.shard_name,
                RedisCommand.key_pattern,
                func.count(RedisCommand.id).label('count')
            ).filter(
                RedisCommand.job_id == job_id,
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
    
    return templates.TemplateResponse("job_detail.html", {
        "request": request,
        "job": job,
        "shards": shards_data,
        "command_types": cmd_types,
        "command_by_shard": command_by_shard,
        "top_patterns": top_patterns,
        "pattern_by_shard": pattern_by_shard,
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
    
    # Build base query
    base_filter = [RedisCommand.job_id == job_id]
    
    if shard_filter:
        base_filter.append(RedisCommand.shard_name == shard_filter)
    
    if command_filter:
        base_filter.append(RedisCommand.command == command_filter.upper())
    
    # Get available shards for filter dropdown
    shards = db.query(MonitorShard).filter(MonitorShard.job_id == job_id).all()
    
    # Get available commands for filter dropdown
    commands = db.query(RedisCommand.command).filter(
        RedisCommand.job_id == job_id
    ).distinct().all()
    commands = sorted([c[0] for c in commands])
    
    # Group by analysis
    if group_by == "key_pattern":
        results = db.query(
            RedisCommand.key_pattern,
            func.count(RedisCommand.id).label('count'),
            func.avg(RedisCommand.key_size_bytes).label('avg_size'),
            func.sum(RedisCommand.key_size_bytes).label('total_size')
        ).filter(*base_filter).filter(
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
        results = db.query(
            RedisCommand.shard_name,
            func.count(RedisCommand.id).label('count'),
            func.sum(RedisCommand.key_size_bytes).label('total_size')
        ).filter(*base_filter).group_by(
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
        results = db.query(
            RedisCommand.command,
            func.count(RedisCommand.id).label('count')
        ).filter(*base_filter).group_by(
            RedisCommand.command
        ).order_by(
            desc('count')
        ).limit(limit).all()
        
        analysis_data = [{
            'name': r[0],
            'count': r[1]
        } for r in results]
    
    elif group_by == "client_ip":
        results = db.query(
            RedisCommand.client_ip,
            func.count(RedisCommand.id).label('count')
        ).filter(*base_filter).filter(
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
        # Individual keys with sizes
        results = db.query(
            RedisCommand.key,
            RedisCommand.shard_name,
            func.count(RedisCommand.id).label('count'),
            func.max(RedisCommand.key_size_bytes).label('size')
        ).filter(*base_filter).filter(
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
    
    else:
        analysis_data = []
    
    # Get overall stats
    total_commands = db.query(func.count(RedisCommand.id)).filter(
        RedisCommand.job_id == job_id
    ).scalar() or 0
    
    unique_keys = db.query(func.count(func.distinct(RedisCommand.key))).filter(
        RedisCommand.job_id == job_id
    ).scalar() or 0
    
    unique_patterns = db.query(func.count(func.distinct(RedisCommand.key_pattern))).filter(
        RedisCommand.job_id == job_id
    ).scalar() or 0
    
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
    
    # Get command distribution
    command_dist = db.query(
        RedisCommand.command,
        func.count(RedisCommand.id).label('count')
    ).filter(
        RedisCommand.job_id == job_id,
        RedisCommand.shard_name == shard_name
    ).group_by(
        RedisCommand.command
    ).order_by(
        desc('count')
    ).limit(10).all()
    
    # Get top key patterns
    top_patterns = db.query(
        RedisCommand.key_pattern,
        func.count(RedisCommand.id).label('count'),
        func.avg(RedisCommand.key_size_bytes).label('avg_size')
    ).filter(
        RedisCommand.job_id == job_id,
        RedisCommand.shard_name == shard_name,
        RedisCommand.key_pattern.isnot(None)
    ).group_by(
        RedisCommand.key_pattern
    ).order_by(
        desc('count')
    ).limit(20).all()
    
    # Get top individual keys
    top_keys = db.query(
        RedisCommand.key,
        func.count(RedisCommand.id).label('count'),
        func.max(RedisCommand.key_size_bytes).label('size')
    ).filter(
        RedisCommand.job_id == job_id,
        RedisCommand.shard_name == shard_name,
        RedisCommand.key.isnot(None)
    ).group_by(
        RedisCommand.key
    ).order_by(
        desc('count')
    ).limit(30).all()
    
    # Get recent commands
    recent_commands = db.query(RedisCommand).filter(
        RedisCommand.job_id == job_id,
        RedisCommand.shard_name == shard_name
    ).order_by(
        desc(RedisCommand.timestamp)
    ).limit(100).all()
    
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
    
    # Calculate actual commands from database for accuracy
    actual_total = db.query(func.count(RedisCommand.id)).filter(
        RedisCommand.job_id == job_id
    ).scalar() or 0
    
    return {
        "job_id": job_id,
        "status": job.status.value,
        "total_commands": max(job.total_commands, actual_total),
        "error_message": job.error_message,
        "shards": shards_status
    }


@app.get("/api/jobs/{job_id}/chart-data")
async def get_chart_data(
    job_id: str,
    chart_type: str = "shard_distribution",
    db: Session = Depends(get_db)
):
    """Get chart data for visualizations."""
    if chart_type == "shard_distribution":
        results = db.query(
            RedisCommand.shard_name,
            func.count(RedisCommand.id).label('count')
        ).filter(
            RedisCommand.job_id == job_id
        ).group_by(
            RedisCommand.shard_name
        ).all()
        
        return {
            "labels": [r[0] for r in results],
            "values": [r[1] for r in results]
        }
    
    elif chart_type == "command_distribution":
        results = db.query(
            RedisCommand.command,
            func.count(RedisCommand.id).label('count')
        ).filter(
            RedisCommand.job_id == job_id
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
        results = db.query(
            RedisCommand.key_pattern,
            func.count(RedisCommand.id).label('count')
        ).filter(
            RedisCommand.job_id == job_id,
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
    
    # Delete commands first
    db.query(RedisCommand).filter(RedisCommand.job_id == job_id).delete()
    db.query(KeySizeCache).filter(KeySizeCache.job_id == job_id).delete()
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
# CUSTOM SQL QUERY
# =============================================================================

@app.get("/query", response_class=HTMLResponse)
async def query_page(
    request: Request,
    sql: Optional[str] = None,
    job_id: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Custom SQL query page."""
    results = None
    error = None
    columns = []
    
    # Get all jobs for dropdown
    jobs = db.query(MonitorJob).order_by(desc(MonitorJob.created_at)).all()
    
    if sql:
        try:
            # Safety: only allow SELECT queries
            if not sql.strip().upper().startswith("SELECT"):
                error = "Only SELECT queries are allowed"
            else:
                result = db.execute(text(sql))
                columns = list(result.keys())
                results = [dict(row._mapping) for row in result.fetchall()]
        except Exception as e:
            error = str(e)
    
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

