# CLI Reference (Legacy)

> **Note:** The CLI is maintained for scripting and automation use cases. For interactive use, we recommend the [Web GUI](../README.md).

## Commands

### 1. `elasticache-monitor` - Automated Monitoring

**Auto-discovers replica endpoints and monitors all shards.**

```bash
# Basic usage
elasticache-monitor -c my-cluster -p YOUR_PASSWORD

# With SQLite database storage for custom queries
elasticache-monitor -c my-cluster -p YOUR_PASSWORD --save-to-db

# With bandwidth estimation (samples actual key sizes)
elasticache-monitor -c my-cluster -p YOUR_PASSWORD --estimate-bandwidth

# Full power: database + bandwidth + longer duration
elasticache-monitor -c my-cluster -p YOUR_PASSWORD -d 180 --save-to-db --estimate-bandwidth

# Custom duration and output directory
elasticache-monitor \
    -c my-cluster \
    -p YOUR_PASSWORD \
    -d 180 \
    -o /path/to/reports

# Different region
elasticache-monitor -c my-cluster -p PASSWORD -r us-east-1
```

**Options:**
- `-c, --cluster-id`: Cluster ID (required)
- `-p, --password`: Redis password (required)
- `-r, --region`: AWS region (default: ap-south-1)
- `--profile`: AWS profile name (e.g., production)
- `-d, --duration`: Duration in seconds (default: 60)
- `-o, --output-dir`: Output directory (default: ./reports)
- `--no-save-logs`: Don't save raw monitor logs
- `--save-to-db`: Save logs to SQLite database for custom queries
- `--db-path`: SQLite database path (default: ./reports/monitor_logs.db)
- `--estimate-bandwidth`: Estimate bandwidth by sampling actual key sizes (~10s extra)
- `--use-primary`: Use primary endpoints (⚠️ not recommended for production)
- `-e, --endpoints`: Manual endpoints (bypasses auto-discovery)

**Output:**
- Console analysis with hot shard detection
- Text report: `./reports/report_<cluster>_<timestamp>.txt`
- Markdown report: `./reports/report_<cluster>_<timestamp>.md`
- JSON data: `./reports/data_<cluster>_<timestamp>.json`
- Raw logs: `./reports/raw_logs/<shard>_<timestamp>.log`
- SQLite database: `./reports/monitor_logs.db` (if --save-to-db enabled)

### 2. `elasticache-endpoints` - Discover Endpoints

**List all shard endpoints from AWS.**

```bash
# List all endpoints
elasticache-endpoints -c my-cluster -r ap-south-1

# Get replica endpoints (recommended for production)
elasticache-endpoints -c my-cluster --replica-only -f monitor-cmd

# Get in simple format for scripting
elasticache-endpoints -c my-cluster --replica-only -f endpoints
```

**Options:**
- `-c, --cluster-id`: Cluster ID
- `-r, --region`: AWS region (default: ap-south-1)
- `--replica-only`: Only replica endpoints (⭐ recommended)
- `--primary-only`: Only primary endpoints
- `-f, --format`: Output format (table, monitor-cmd, endpoints)

### 3. `elasticache-analyze` - Analyze Logs

**Analyze pre-collected monitor logs.**

```bash
# Analyze single log
elasticache-analyze shard1.log

# Compare multiple logs
elasticache-analyze --compare shard1.log shard2.log shard3.log
```

### 4. `elasticache-schedule` - Scheduled Monitoring

**Run monitoring on a schedule.**

```bash
# Create config
cp config.yaml.example config.yaml
# Edit config.yaml

# Set password
export REDIS_PASSWORD="your-password"

# Run once
elasticache-schedule --once

# Run every 30 minutes
elasticache-schedule --interval 1800
```

### 5. `elasticache-query` - Database Queries

**Query and analyze stored monitor logs from SQLite database.**

```bash
# Show statistics for all data
elasticache-query --stats

# Show stats for specific session
elasticache-query --session 1 --stats

# Find all GET commands on shard 0001
elasticache-query --shard 0001 --command GET --limit 50

# Find keys matching pattern
elasticache-query --pattern "ratelimit:*" --limit 20

# Custom SQL query - top commands
elasticache-query --sql "SELECT command, COUNT(*) as cnt FROM monitor_logs GROUP BY command ORDER BY cnt DESC LIMIT 10"
```

**Options:**
- `--db-path`: Path to database (default: ./reports/monitor_logs.db)
- `--session, -s`: Filter by session ID
- `--cluster, -c`: Filter by cluster ID
- `--shard`: Filter by shard name
- `--command, -cmd`: Filter by command type (GET, SET, etc.)
- `--pattern, -k`: Filter by key pattern
- `--limit, -l`: Limit results (default: 100)
- `--stats`: Show statistics summary
- `--sql`: Execute custom SQL query

---

## Bypass Options

### Manual Endpoints (Bypass Auto-Discovery)

```bash
# Single endpoint
elasticache-monitor \
    -p YOUR_PASSWORD \
    -e redis.example.com:6379:shard-1

# Multiple endpoints
elasticache-monitor \
    -p YOUR_PASSWORD \
    -e host1.example.com:6379:shard-1 \
    -e host2.example.com:6379:shard-2
```

### Use Primary Nodes

⚠️ **WARNING:** Not recommended for production!

```bash
elasticache-monitor \
    -c my-cluster \
    -p YOUR_PASSWORD \
    --use-primary
```

---

## Bandwidth Estimation

Enable with `--estimate-bandwidth` to sample actual key sizes:

```bash
elasticache-monitor -c my-cluster -p PASS -d 120 --estimate-bandwidth
```

This samples actual keys using `MEMORY USAGE` to calculate bandwidth estimates per shard and key pattern.

---

## Environment Variables

```bash
export REDIS_PASSWORD="your-password"
export AWS_REGION="ap-south-1"
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
```

