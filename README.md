# ElastiCache Hot Shard Debugger

A comprehensive Python toolkit for debugging hot shard issues and analyzing uneven distribution of keys or queries in AWS ElastiCache (Redis/Valkey) clusters.

**Built with Python 3.12+ and managed with [uv](https://github.com/astral-sh/uv).**

## Table of Contents

- [Features](#features)
- [Quick Start](#quick-start)
- [Installation](#installation)
- [How to Run](#how-to-run)
- [CLI Commands](#cli-commands)
- [SQLite Database Usage](#sqlite-database-usage)
- [Understanding Results](#understanding-results)
- [Bandwidth Estimation](#bandwidth-estimation)
- [Bypass Options](#bypass-options)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Production Best Practices](#production-best-practices)
- [Common Issues & Solutions](#common-issues--solutions)
- [Development](#development)
- [AWS Permissions Required](#aws-permissions-required)
- [Support](#support)

---

## ⚠️ Production Safety

**IMPORTANT**: Always use replica/read endpoints for monitoring in production environments. The `MONITOR` command can impact performance on primary nodes.

## Features

- 🤖 **Fully automated** - just provide cluster name and password!
- 🔍 **Real-time monitoring** of multiple shards simultaneously
- 📊 **Hot shard detection** with automatic deviation analysis
- 🔑 **Key pattern analysis** to identify hot keys
- 📈 **QPS comparison** across shards
- 🎯 **Command distribution** analysis
- 👥 **Client connection** tracking
- 🤖 **AWS integration** to auto-discover shard endpoints
- 📅 **Scheduled monitoring** with config file support
- 📝 **Comprehensive reports** in text, Markdown, and JSON formats
- 💾 **SQLite database storage** for custom queries and advanced analysis
- 📡 **Bandwidth estimation** by sampling actual key sizes
- 📦 **Proper Python package** with CLI entry points

---

## Quick Start

### Installation

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Install the package
cd /path/to/elasticache-hot-shard-debug
uv pip install -e .

# Or with make
make install
```

### Run Your First Monitor

```bash
# Monitor a cluster (auto-discovers replica endpoints)
elasticache-monitor \
    -c my-cluster \
    -p YOUR_PASSWORD \
    -d 120

# Or with environment variable
export REDIS_PASSWORD="your-password"
elasticache-monitor -c my-cluster -d 120

# Or with Makefile
make run CLUSTER_ID=my-cluster REDIS_PASSWORD=yourpass DURATION=120
```

### What You'll Get

```
================================================================================
🤖 AUTOMATED ELASTICACHE HOT SHARD MONITOR
================================================================================

Configuration:
  Cluster ID: my-cluster
  Region: ap-south-1
  Duration: 120 seconds
  Output Dir: ./reports
  ⚠️  Using REPLICA endpoints (production safe)

🔍 Discovering replica endpoints from AWS...
✓ Found 3 replica endpoints

🔍 Starting monitoring for 120 seconds...
Progress: [████████████████████████████] 100%

✓ Monitoring complete!

📊 Hot Shard Analysis:
┌────────┬──────────┬─────────────────────┬───────────┐
│ Shard  │ Commands │ Deviation from Avg  │ Status    │
├────────┼──────────┼─────────────────────┼───────────┤
│ shard-2│ 125,450  │ +52.3%              │ 🔥 VERY HOT│
│ shard-1│ 85,230   │ +3.5%               │ ✓ NORMAL  │
│ shard-3│ 68,120   │ -17.2%              │ ✓ NORMAL  │
└────────┴──────────┴─────────────────────┴───────────┘

📁 Reports saved:
   Report: ./reports/report_my-cluster_20251014_143022.txt
   Data:   ./reports/data_my-cluster_20251014_143022.json
   Logs:   ./reports/raw_logs/
```

---

## Installation

### Prerequisites

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) - Fast Python package installer
- AWS credentials configured (for auto-discovery)

### Install uv

If you don't have uv installed:

```bash
# On macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or with pip
pip install uv
```

### Quick Install

```bash
cd /path/to/elasticache-hot-shard-debug

# Install the package
uv pip install -e .

# Or with make
make install
```

### Development Install

For development with testing and linting tools:

```bash
# Install with dev dependencies
uv pip install -e ".[dev]"

# Or with make
make dev
```

### Virtual Environment (Recommended)

`uv` automatically detects the `.python-version` file and creates a Python 3.12 venv:

```bash
# Create Python 3.12 venv (reads .python-version automatically)
uv venv

# Or with make
make venv

# Activate it
source .venv/bin/activate  # On macOS/Linux
# or
.venv\Scripts\activate  # On Windows

# Install
uv pip install -e .

# Or do everything at once with make
make install  # Creates venv if needed, then installs
```

### Verify Installation

```bash
# Check installed commands
elasticache-monitor --help
elasticache-endpoints --help
elasticache-analyze --help
elasticache-schedule --help
elasticache-query --help

# Quick version check
python -c "import elasticache_monitor; print(elasticache_monitor.__version__)"
```

### Makefile Commands

```bash
make help        # Show all available commands
make install     # Install package
make dev         # Install with dev tools
make format      # Format code
make lint        # Check code quality
make clean       # Remove build artifacts
make run CLUSTER_ID=my-cluster REDIS_PASSWORD=pass
```

---

## How to Run

### Prerequisites

1. ✅ AWS credentials configured
2. ✅ Redis/Valkey password
3. ✅ ElastiCache cluster name

### Step-by-Step

#### 1. Initial Setup (First Time Only)

```bash
cd /path/to/elasticache-hot-shard-debug

# Create Python 3.12 venv and install
make install

# Activate the virtual environment
source .venv/bin/activate
```

#### 2. Set Your Password

```bash
# Method 1: Export as environment variable (recommended)
export REDIS_PASSWORD="your-actual-password-here"

# Method 2: Use directly in command (not recommended - visible in history)
# We'll use -p flag directly
```

#### 3. Run the Monitor

```bash
# Basic usage (60 seconds, auto-discovers replicas)
elasticache-monitor \
    -c my-cluster \
    -p YOUR_PASSWORD

# With environment variable (cleaner)
export REDIS_PASSWORD="your-password"
elasticache-monitor -c my-cluster

# Monitor for 2 minutes
elasticache-monitor \
    -c my-cluster \
    -p YOUR_PASSWORD \
    -d 120

# Different region
elasticache-monitor \
    -c my-cluster \
    -p YOUR_PASSWORD \
    -r ap-south-1 \
    -d 120

# Custom output directory
elasticache-monitor \
    -c my-cluster \
    -p YOUR_PASSWORD \
    -d 120 \
    -o /path/to/reports
```

#### 4. Using Makefile (Alternative)

```bash
# Activate venv first
source .venv/bin/activate

# Then run with make
make run CLUSTER_ID=my-cluster REDIS_PASSWORD=yourpass DURATION=120
```

### Complete Example Session

```bash
# Terminal session
cd /path/to/elasticache-hot-shard-debug

# First time setup
make install

# Activate venv
source .venv/bin/activate

# Set password (DO NOT commit this in your .bashrc/.zshrc!)
export REDIS_PASSWORD="your-actual-redis-password"

# Run monitoring
elasticache-monitor \
    -c my-cluster \
    -d 120

# Output will show:
# - Auto-discovery of replica endpoints
# - Progress bar
# - Hot shard analysis
# - Reports saved to ./reports/
```

### View Reports

```bash
# View text report
cat reports/report_my-cluster_*.txt

# View JSON data
cat reports/data_my-cluster_*.json | jq .

# List all reports
ls -lh reports/
```

---

## CLI Commands

After installation, five commands are available:

### 1. `elasticache-monitor` - Automated Monitoring (⭐ Main Tool)

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

### 5. `elasticache-query` - Database Queries (💾 New!)

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

# Find hot shards by QPS
elasticache-query --sql "SELECT shard_name, COUNT(*) / (MAX(timestamp) - MIN(timestamp)) as qps FROM monitor_logs GROUP BY shard_name ORDER BY qps DESC"

# Find top clients by IP
elasticache-query --sql "SELECT client_ip, COUNT(*) as requests FROM monitor_logs GROUP BY client_ip ORDER BY requests DESC LIMIT 10"

# Show all monitoring sessions
elasticache-query --sql "SELECT * FROM monitoring_sessions ORDER BY start_time DESC"

# Time-based analysis - commands per minute
elasticache-query --sql "SELECT strftime('%Y-%m-%d %H:%M', datetime_utc) as minute, COUNT(*) as commands FROM monitor_logs GROUP BY minute ORDER BY minute DESC LIMIT 20"
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

## SQLite Database Usage

### Overview

The ElastiCache Monitor supports storing all captured monitor logs in a **SQLite database** for advanced querying and analysis. This is especially useful for high-traffic production environments where you want to:

- Run custom SQL queries to analyze patterns
- Compare data across multiple monitoring sessions
- Perform time-series analysis
- Identify trends over longer periods
- Query specific shards, commands, or key patterns
- Track client behavior and distribution

### Quick Start

#### 1. Capture Data with --save-to-db

```bash
# Monitor and save to database
elasticache-monitor \
    -c my-cluster \
    -p YOUR_PASSWORD \
    -d 60 \
    --save-to-db

# You'll see output like:
# 💾 Initializing database: ./reports/monitor_logs.db
# ✓ Database session #1 started
# ... monitoring happens ...
# ✓ Database session #1 completed (125,432 commands)
# 📁 Reports saved:
#    Database: ./reports/monitor_logs.db
# 💡 Query database:
#    elasticache-query --db-path ./reports/monitor_logs.db
```

#### 2. Query the Database

```bash
# Show statistics
elasticache-query --stats

# Query specific session
elasticache-query --session 1 --stats

# Find commands on a specific shard
elasticache-query --shard 0001 --limit 100

# Find keys matching a pattern
elasticache-query --pattern "ratelimit:*" --limit 50
```

### Database Schema

#### Table: monitor_logs

Stores every captured command with full context.

| Column          | Type   | Description                              |
|-----------------|--------|------------------------------------------|
| id              | INT    | Auto-incrementing primary key            |
| cluster_id      | TEXT   | Cluster identifier                       |
| shard_name      | TEXT   | Shard name (e.g., "0001", "0002")        |
| timestamp       | REAL   | Unix timestamp (with milliseconds)       |
| datetime_utc    | TEXT   | Human-readable UTC datetime              |
| client_address  | TEXT   | Full client address (IP:port)            |
| client_ip       | TEXT   | Extracted client IP only                 |
| command         | TEXT   | Redis command (GET, SET, etc.)           |
| key             | TEXT   | The key being accessed (first 500 chars) |
| key_pattern     | TEXT   | Extracted pattern (e.g., "user:{UUID}")  |
| args            | TEXT   | JSON array of command arguments          |
| raw_line        | TEXT   | Full raw monitor line                    |
| collection_time | TEXT   | When this was collected (session time)   |

**Indexes:**
- `idx_cluster_shard` on (cluster_id, shard_name)
- `idx_timestamp` on timestamp
- `idx_command` on command
- `idx_key_pattern` on key_pattern
- `idx_client_ip` on client_ip

#### Table: monitoring_sessions

Metadata about each monitoring run.

| Column           | Type   | Description                    |
|------------------|--------|--------------------------------|
| id               | INT    | Session ID                     |
| cluster_id       | TEXT   | Cluster identifier             |
| start_time       | TEXT   | Session start time (UTC)       |
| end_time         | TEXT   | Session end time (UTC)         |
| duration_seconds | INT    | Configured duration            |
| num_shards       | INT    | Number of shards monitored     |
| total_commands   | INT    | Total commands captured        |
| config           | TEXT   | JSON with monitoring config    |

### Example Queries

#### Basic Queries

```bash
# Show all sessions
elasticache-query --sql "SELECT * FROM monitoring_sessions ORDER BY start_time DESC"

# Total commands captured
elasticache-query --sql "SELECT COUNT(*) as total FROM monitor_logs"

# Commands per cluster
elasticache-query --sql "SELECT cluster_id, COUNT(*) as commands FROM monitor_logs GROUP BY cluster_id"
```

#### Hot Shard Analysis

```bash
# Commands per shard
elasticache-query --sql "
SELECT 
    shard_name,
    COUNT(*) as total_commands,
    COUNT(DISTINCT command) as unique_commands,
    COUNT(DISTINCT client_ip) as unique_clients
FROM monitor_logs
GROUP BY shard_name
ORDER BY total_commands DESC
"

# QPS per shard
elasticache-query --sql "
SELECT 
    shard_name,
    COUNT(*) as commands,
    ROUND((MAX(timestamp) - MIN(timestamp)), 2) as duration_seconds,
    ROUND(COUNT(*) / (MAX(timestamp) - MIN(timestamp)), 2) as qps
FROM monitor_logs
GROUP BY shard_name
ORDER BY qps DESC
"
```

#### Command Analysis

```bash
# Top commands globally
elasticache-query --sql "
SELECT command, COUNT(*) as count
FROM monitor_logs
GROUP BY command
ORDER BY count DESC
LIMIT 20
"

# Commands per shard
elasticache-query --sql "
SELECT shard_name, command, COUNT(*) as count
FROM monitor_logs
GROUP BY shard_name, command
ORDER BY shard_name, count DESC
"
```

#### Key Pattern Analysis

```bash
# Top key patterns
elasticache-query --sql "
SELECT key_pattern, COUNT(*) as access_count
FROM monitor_logs
WHERE key_pattern IS NOT NULL
GROUP BY key_pattern
ORDER BY access_count DESC
LIMIT 50
"

# Find hot keys (accessed >100 times)
elasticache-query --sql "
SELECT key, COUNT(*) as access_count
FROM monitor_logs
WHERE key IS NOT NULL
GROUP BY key
HAVING access_count > 100
ORDER BY access_count DESC
LIMIT 100
"
```

#### Client Analysis

```bash
# Top clients by request count
elasticache-query --sql "
SELECT client_ip, COUNT(*) as requests
FROM monitor_logs
WHERE client_ip IS NOT NULL
GROUP BY client_ip
ORDER BY requests DESC
LIMIT 50
"
```

#### Time-Series Analysis

```bash
# Commands per minute
elasticache-query --sql "
SELECT 
    strftime('%Y-%m-%d %H:%M', datetime_utc) as minute,
    COUNT(*) as commands
FROM monitor_logs
GROUP BY minute
ORDER BY minute DESC
LIMIT 60
"
```

### CLI Shortcuts

Instead of typing SQL, use built-in filters:

```bash
# Find all GET commands on shard 0001
elasticache-query --shard 0001 --command GET --limit 100

# Find keys with "user" in pattern
elasticache-query --pattern "user" --limit 50

# Show recent commands from specific cluster
elasticache-query --cluster my-cluster --limit 200

# Combine filters
elasticache-query --shard 0002 --command SET --pattern "lock:*" --limit 50
```

### Tips and Best Practices

#### 1. Monitor for Longer Periods

For meaningful analysis, monitor for at least 2-5 minutes in production:

```bash
elasticache-monitor -c my-cluster -p PASS -d 300 --save-to-db
```

#### 2. Multiple Sessions

Run monitoring at different times and compare:

```bash
# Morning traffic
elasticache-monitor -c my-cluster -p PASS -d 120 --save-to-db

# Evening traffic
elasticache-monitor -c my-cluster -p PASS -d 120 --save-to-db

# Compare
elasticache-query --sql "SELECT * FROM monitoring_sessions"
elasticache-query --session 1 --stats
elasticache-query --session 2 --stats
```

#### 3. Export Results

Save query results to files for sharing:

```bash
# Using SQLite CLI directly
sqlite3 reports/monitor_logs.db "SELECT * FROM monitor_logs WHERE shard_name='0001' LIMIT 100" > shard_0001_analysis.txt

# Or export to CSV
sqlite3 -csv reports/monitor_logs.db "SELECT shard_name, command, COUNT(*) FROM monitor_logs GROUP BY shard_name, command" > command_distribution.csv
```

#### 4. Database Management

```bash
# Check database size
du -h reports/monitor_logs.db

# Compact database
sqlite3 reports/monitor_logs.db "VACUUM;"

# Backup database
cp reports/monitor_logs.db reports/monitor_logs_backup_$(date +%Y%m%d).db
```

---

## Understanding Results

### Hot Shard Detection

```
Hot Shard Analysis:
┌────────┬──────────┬─────────────────────┬───────────┐
│ Shard  │ Commands │ Deviation from Avg  │ Status    │
├────────┼──────────┼─────────────────────┼───────────┤
│ shard-2│ 125,450  │ +52.3%              │ 🔥 VERY HOT│
│ shard-1│ 85,230   │ +3.5%               │ ✓ NORMAL  │
│ shard-3│ 68,120   │ -17.2%              │ ✓ NORMAL  │
└────────┴──────────┴─────────────────────┴───────────┘
```

**Status Indicators:**
- 🔥 **VERY HOT**: >50% above average (investigate immediately)
- ⚠️ **HOT**: 25-50% above average (monitor closely)
- ✓ **NORMAL**: Within ±25% of average
- ❄️ **COLD**: >25% below average

### Key Pattern Analysis

The tool automatically groups similar keys:

```
ratelimit:{APP:getUser}:{HASH}             → Rate limiting pattern
PRODUCTION:userId:{USERID}:date:{DATE}...  → User-specific pattern
lock:{TYPE}:{USERID}                        → Distributed locks
```

**Patterns:**
- `{UUID}` - UUIDs
- `{HASH}` - MD5/SHA hashes
- `{USERID}` - User IDs (10+ digits)
- `{DATE}` - Date patterns (YYYY-MM-DD)
- `{TIMESTAMP}` - Unix timestamps
- `{IP}` - IP addresses

### Hot Key Detection

Keys with >1000 accesses in 60 seconds are likely hot keys that need:
- Client-side caching
- Key redesign
- Load distribution

---

## Bandwidth Estimation

**Identify hot shards by network bandwidth, not just query count!**

Enable with `--estimate-bandwidth` to sample actual key sizes:

```bash
elasticache-monitor -c my-cluster -p PASS -d 120 --estimate-bandwidth
```

### What it does:

1. Monitors commands as usual
2. After monitoring, samples actual keys to get their sizes using `MEMORY USAGE`
3. Calculates bandwidth estimates per shard and key pattern

### Example output:

```
📊 Estimated Bandwidth Analysis:

Shard  │ Commands │ Est. Bandwidth │ KB/Command
───────┼──────────┼────────────────┼────────────
0001   │ 10,234   │ 145.32 MB      │ 14.2 KB
0002   │ 8,456    │ 289.45 MB      │ 34.2 KB    ← 🔥 2x bandwidth!
0003   │ 9,123    │ 132.18 MB      │ 14.5 KB

⚠️  0002 has 98% more bandwidth than average!

🔥 Top Bandwidth Consumers:

Shard │ Key Pattern              │ Accesses │ Avg Size │ Est. Total
──────┼──────────────────────────┼──────────┼──────────┼────────────
0002  │ user:{UUID}:profile      │ 1,234    │ 124.5 KB │ 153.6 MB
0002  │ logs:{DATE}              │ 456      │ 85.2 KB  │ 38.9 MB
0001  │ cache:{HASH}             │ 5,678    │ 8.5 KB   │ 48.3 MB
```

### Why this matters:

- A shard with fewer queries but larger responses can have higher bandwidth
- Identifies which key patterns consume most bandwidth
- Helps optimize data structures and caching strategies

### Accuracy:

- ~80-90% accurate compared to actual network bytes
- Based on real key sizes sampled from Redis
- Accounts for command types (GET vs HGETALL vs LRANGE)

### Performance:

- Adds ~10 seconds to analysis time
- Uses replica endpoints (production safe)
- Samples up to 10 keys per pattern

---

## Bypass Options

Sometimes you need to bypass the default safe behavior. Here's how:

### 1. Bypass Auto-Discovery (Manual Endpoints)

Use `--endpoints` to manually specify endpoints instead of AWS auto-discovery.

**Why?**
- No AWS credentials available
- Want to monitor specific shards only
- Testing/development
- Non-AWS Redis clusters

**Usage:**

```bash
# Single endpoint
elasticache-monitor \
    -p YOUR_PASSWORD \
    -e redis.example.com:6379:shard-1

# Multiple endpoints
elasticache-monitor \
    -p YOUR_PASSWORD \
    -e host1.example.com:6379:shard-1 \
    -e host2.example.com:6379:shard-2 \
    -e host3.example.com:6379:shard-3 \
    -d 120
```

**Format:** `--endpoints HOST:PORT:NAME`

### 2. Bypass Replica-Only (Use Primaries)

Use `--use-primary` to monitor primary nodes instead of replicas.

⚠️ **WARNING:** Not recommended for production! The MONITOR command can impact performance on primary nodes.

**Usage:**

```bash
# Use primary endpoints (with auto-discovery)
elasticache-monitor \
    -c my-cluster \
    -p YOUR_PASSWORD \
    --use-primary
```

### When to Use Each Bypass

| Bypass Option | When to Use | Risk Level |
|---------------|-------------|------------|
| `--endpoints` | No AWS creds, specific shards, non-AWS | ✅ Safe |
| `--use-primary` | No replicas, dev/test only | ⚠️ High |

### Safety Tips

**DO ✅**

1. **Use replicas when possible**
2. **Test with short duration first**
3. **Monitor during off-peak hours**

**DON'T ❌**

1. **Don't use --use-primary in production without understanding impact**
2. **Don't monitor primary during peak hours**
3. **Don't run long durations (>5 min) on primaries**

---

## Project Structure

```
elasticache-hot-shard-debug/
├── src/
│   └── elasticache_monitor/          # Main package
│       ├── __init__.py                # Package initialization
│       ├── cli.py                     # CLI entry points
│       ├── monitor.py                 # Shard monitoring logic
│       ├── endpoints.py               # AWS endpoint discovery
│       ├── analyzer.py                # Log file analysis
│       ├── database.py                # SQLite operations
│       ├── bandwidth.py               # Key size sampling
│       ├── reporter.py                # Report generation
│       └── utils.py                   # Shared utilities
│
├── pyproject.toml                     # Project metadata & dependencies (uv/pip)
├── .python-version                    # Python version specification (3.12)
├── Makefile                           # Common tasks automation
├── .gitignore                         # Git ignore patterns
│
├── README.md                          # This file
├── CURSOR_CONTEXT.md                  # AI assistant context
│
└── config.yaml.example                # Example configuration
```

### Module Responsibilities

- **cli.py**: Command-line interface entry points with Click
- **monitor.py**: ShardMonitor class for monitoring individual shards with TLS
- **endpoints.py**: AWS boto3 integration for endpoint discovery
- **analyzer.py**: Parses monitor log files and extracts statistics
- **database.py**: SQLite storage for persistent querying
- **bandwidth.py**: Samples key sizes to estimate NetworkBytesOut
- **reporter.py**: Generates comprehensive reports with hot shard detection
- **utils.py**: Shared utility functions and monitor line parsing

### Data Flow

```
AWS ElastiCache
    ↓
[endpoints.py] ← boto3 API call
    ↓
Endpoint List
    ↓
[monitor.py] ← Redis MONITOR command
    ↓
Raw Monitor Data
    ↓
[utils.py] ← Parse & Extract patterns
    ↓
Statistics Dictionary
    ↓
[reporter.py] ← Generate & Display
    ↓
Console Output + Files + Database
```

---

## Configuration

### Using Config File

```yaml
# config.yaml
cluster:
  id: "my-cluster"
  region: "ap-south-1"

redis:
  password: "${REDIS_PASSWORD}"

monitoring:
  duration: 120
  use_replicas: true

output:
  directory: "./reports"
  save_raw_logs: true
```

### Environment Variables

```bash
export REDIS_PASSWORD="your-password"
export AWS_REGION="ap-south-1"
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
```

---

## Production Best Practices

### ✅ DO:

- Always use `--replica-only` or let auto-discover handle it
- Monitor during normal business hours
- Run for 60-300 seconds for meaningful data
- Save reports for historical analysis
- Run multiple times to identify patterns
- Use `--save-to-db` for advanced analysis
- Use `--estimate-bandwidth` to correlate with CloudWatch

### ❌ DON'T:

- Don't monitor primary shards in production
- Don't run for too long (>5 minutes) continuously
- Don't ignore hot shard warnings
- Don't commit config.yaml with passwords

---

## Common Issues & Solutions

### Hot Shards

**Cause**: Uneven key distribution, hot keys, poor hash slot usage

**Solutions:**
1. Check key patterns in reports
2. Use hash tags `{...}` carefully
3. Implement client-side caching for hot keys
4. Consider key redesign

### Connection Issues

**Symptoms**: Connection timeout, auth failures

**Solutions:**
1. Verify security groups allow your IP
2. Check VPN connection if required
3. Verify password is correct
4. Ensure using correct endpoint

### No Replica Endpoints

**Symptoms**: "No replica endpoints found"

**Solutions:**
1. Add replicas to your cluster (recommended)
2. Use `--use-primary` flag (not recommended for production)

### Authentication Required

```bash
# Test connection manually
redis-cli --tls \
    -h YOUR_ENDPOINT \
    -p 6379 \
    -a YOUR_PASSWORD \
    PING
# Should return: PONG
```

### AWS Credentials Not Configured

```bash
# Configure AWS CLI
aws configure

# Or set environment variables
export AWS_ACCESS_KEY_ID="your-key"
export AWS_SECRET_ACCESS_KEY="your-secret"
export AWS_DEFAULT_REGION="ap-south-1"
```

### Troubleshooting Installation

#### uv not found

```bash
# Make sure uv is in your PATH
which uv

# Or install it
curl -LsSf https://astral.sh/uv/install.sh | sh
```

#### Redis Connection Issues

- Verify security groups allow your IP
- Check if you're on VPN (if required)
- Verify password is correct
- Ensure using replica endpoints in production

---

## Development

```bash
# Install with dev dependencies
make dev

# Format code
make format

# Lint code
make lint

# Clean build artifacts
make clean
```

---

## AWS Permissions Required

```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "elasticache:DescribeReplicationGroups",
                "elasticache:DescribeCacheClusters"
            ],
            "Resource": "*"
        }
    ]
}
```

---

## Support

For issues or questions:
1. Check this README for installation help
2. Check [CURSOR_CONTEXT.md](CURSOR_CONTEXT.md) for AI assistant context
3. Review the SQLite Database Usage section for query examples

---

**Version**: 1.0.0  
**Python**: 3.12+  
**Package Manager**: uv  
**Dependencies**: redis, boto3, click, tabulate, colorama, pyyaml

