# ElastiCache Hot Shard Debugger - Context for AI Assistant

## Project Purpose
This is a Python toolkit to debug hot shards and uneven key distribution in AWS ElastiCache (Redis/Valkey) clusters. The primary use case is identifying why certain shards have disproportionately high **NetworkBytesOut** metrics in CloudWatch.

## Key Problem Being Solved
- **Hot Shard Detection**: One shard (e.g., 0001-002) consistently shows 10x higher NetworkBytesOut than others
- **Root Cause**: Large sorted sets (ZSETs) being fully fetched via `ZREVRANGE` commands
- **Specific Culprit**: Keys like `large_sortedset:app:2025-10-17` (100K+ members, ~10MB each)
- **Distribution Issue**: While keys with different dates hash to different shards, there's a concentration of these large keys on certain shards

## Architecture

### Core Components
1. **Monitoring** (`src/elasticache_monitor/monitor.py`): Uses Redis `MONITOR` command to capture real-time operations
2. **Analysis** (`src/elasticache_monitor/analyzer.py`): Parses monitor logs and identifies patterns
3. **Database** (`src/elasticache_monitor/database.py`): SQLite storage for persistent querying
4. **Bandwidth Estimation** (`src/elasticache_monitor/bandwidth.py`): Samples key sizes to estimate NetworkBytesOut
5. **Endpoint Discovery** (`src/elasticache_monitor/endpoints.py`): AWS API integration to find cluster endpoints

### Technology Stack
- **Python 3.12** with `uv` for dependency management
- **redis-py**: Redis client with SSL support
- **boto3**: AWS API for ElastiCache discovery
- **SQLite**: Local database for log analysis
- **Click**: CLI framework

## Key Technical Concepts

### Redis Cluster Architecture
- **Hash Slots**: 16384 slots distributed across shards
- **Key Distribution**: CRC16(key) % 16384 determines shard placement
- **Hash Tags**: Keys like `{user123}:session` use the tagged portion for slot calculation
- **Cluster Mode**: Each shard has primary + replicas

### Monitoring Strategy
- **Monitor Replicas**: Production safety - monitor read replicas, not primaries
- **SSL Connections**: ElastiCache requires TLS
- **Command Parsing**: Redis MONITOR output format: `timestamp [db client] "command" "arg1" "arg2"`
- **Batching**: Commands buffered and written to SQLite in batches for performance

### Bandwidth Analysis
- **MEMORY USAGE**: Samples key sizes to estimate bandwidth
- **Command Types**: Different commands have different bandwidth impacts (GET vs ZREVRANGE)
- **NetworkBytesOut**: Correlates with large key retrievals, especially sorted sets

## Common Workflows

### 1. Basic Monitoring
```bash
# Auto-discover endpoints and monitor for 2 minutes
elasticache-monitor -c cluster-name -p password -d 120

# Save to database for later analysis
elasticache-monitor -c cluster-name -p password -d 120 --save-to-db
```

### 2. Database Queries
```bash
# Find most frequent keys
elasticache-query "SELECT key_name, COUNT(*) as count FROM commands 
                   WHERE key_name IS NOT NULL 
                   GROUP BY key_name ORDER BY count DESC LIMIT 20"

# Find ZREVRANGE commands on specific shard
elasticache-query "SELECT key_name, COUNT(*) as count FROM commands 
                   WHERE command = 'zrevrange' AND shard LIKE '%0001%'
                   GROUP BY key_name ORDER BY count DESC"
```

### 3. Bandwidth Estimation
```bash
# Sample key sizes and estimate bandwidth per shard
elasticache-monitor -c cluster-name -p password -d 120 --estimate-bandwidth
```

### 4. Bypass Auto-Discovery
```bash
# If AWS API doesn't work, manually specify endpoints
elasticache-monitor -c cluster-name -p password -d 120 \
  --endpoints "replica1.cache.amazonaws.com:6379,replica2.cache.amazonaws.com:6379"
```

## File Structure
```
.
├── src/elasticache_monitor/
│   ├── __init__.py
│   ├── cli.py              # Main CLI entry points
│   ├── monitor.py          # Redis MONITOR command handling
│   ├── analyzer.py         # Log parsing and pattern detection
│   ├── database.py         # SQLite operations
│   ├── bandwidth.py        # Key size sampling
│   ├── endpoints.py        # AWS ElastiCache API
│   ├── reporter.py         # Report generation (console + markdown)
│   └── utils.py            # Shared utilities
├── reports/                # Generated reports and database
├── pyproject.toml          # uv project configuration
├── README.md               # Main documentation
├── QUICKSTART.md           # Quick start guide
├── SQLITE_USAGE.md         # Database query examples
├── HOW_TO_RUN.md           # Detailed usage instructions
├── BYPASS_OPTIONS.md       # Manual endpoint configuration
└── INSTALL.md              # Installation guide
```

## CLI Commands
```bash
# Auto-monitor (main command)
elasticache-monitor -c CLUSTER -p PASSWORD -d DURATION [--save-to-db] [--estimate-bandwidth]

# Get endpoints only (for debugging)
elasticache-endpoints -c CLUSTER

# Analyze existing logs (legacy)
elasticache-analyze -i input.log

# Query database
elasticache-query "SQL QUERY"
```

## Known Issues & Solutions

### Issue 1: SSL Connection Errors
- **Problem**: `SSLConnection object has no attribute 'socket'`
- **Solution**: Use `conn._sock` for SSL connections instead of `conn.socket`

### Issue 2: Empty Endpoint Discovery
- **Problem**: Cluster Mode Enabled clusters don't return endpoints from `describe_replication_groups`
- **Solution**: Query `describe_cache_clusters` and infer roles from naming patterns (`-001` = primary, `-002` = replica)

### Issue 3: Database Threading Errors
- **Problem**: `SQLite objects created in a thread can only be used in that same thread`
- **Solution**: Each monitoring thread creates its own database connection

### Issue 4: Monitor Showing Only Connection Commands
- **Problem**: Only seeing AUTH, CLIENT, PING commands despite high traffic
- **Solution**: Use `redis-py`'s built-in `monitor()` context manager for proper MONITOR output parsing

## Environment Variables
```bash
export AWS_PROFILE=production      # AWS credentials profile
export AWS_REGION=ap-south-1       # ElastiCache region
```

## Production Safety
- **Always monitor replicas**: Use `--use-primary` flag only for testing
- **Short durations**: 2-5 minutes is usually sufficient
- **Off-peak monitoring**: Run during low-traffic periods when possible
- **Sanitize data**: Use sanitization queries before sharing reports

## Performance Considerations
- **Batch Size**: SQLite inserts batched (100 commands) for performance
- **Sampling**: Bandwidth estimation samples max 50 keys per pattern
- **Duration**: Longer monitoring = more data but more load on replica
- **Threading**: Each shard monitored in separate thread

## Common Queries (from SQLITE_USAGE.md)

### Find Hot Keys
```sql
SELECT key_name, COUNT(*) as access_count, command
FROM commands 
WHERE key_name IS NOT NULL 
GROUP BY key_name, command 
ORDER BY access_count DESC 
LIMIT 50;
```

### Shard-Specific Analysis
```sql
SELECT command, COUNT(*) as count
FROM commands 
WHERE shard LIKE '%0001%'
GROUP BY command 
ORDER BY count DESC;
```

### Large Key Operations
```sql
SELECT key_name, command, shard, COUNT(*) as count
FROM commands 
WHERE command IN ('zrevrange', 'lrange', 'smembers', 'hgetall')
GROUP BY key_name, command, shard 
ORDER BY count DESC 
LIMIT 30;
```

## Next Steps for New Users
1. **Install**: `uv venv && uv pip install -e .`
2. **Test endpoints**: `elasticache-endpoints -c your-cluster`
3. **Quick monitor**: `elasticache-monitor -c your-cluster -p password -d 60`
4. **Full analysis**: `elasticache-monitor -c your-cluster -p password -d 120 --save-to-db --estimate-bandwidth`
5. **Query results**: `elasticache-query "SELECT ..."` or check `reports/` directory

## Real-World Example
**Problem**: Shard 0001 showing 100MB/s NetworkBytesOut, others showing 10MB/s

**Investigation**:
1. Ran monitoring with database: `elasticache-monitor -c my-cluster -p XXX -d 120 --save-to-db`
2. Queried ZREVRANGE commands: Found `large_sortedset:app:2025-10-17` accessed frequently
3. Checked key size: `MEMORY USAGE large_sortedset:app:2025-10-17` = 10MB
4. Verified shard: `CLUSTER KEYSLOT large_sortedset:app:2025-10-17` = slot in shard 0001
5. **Root Cause**: Application fetching entire 100K-member sorted set on each request

**Solution**: Implement pagination (fetch top 100 instead of all 100K members)

## Tips for AI Assistants
- This is a **debugging tool**, not a production monitoring system
- Focus on **NetworkBytesOut** analysis, not just command counts
- Always suggest monitoring **replicas** for production
- SQLite database is the most powerful feature - encourage its use
- Bandwidth estimation helps correlate tool findings with CloudWatch metrics
- Key patterns with large sorted sets are critical to identify - they often cause hot shards

