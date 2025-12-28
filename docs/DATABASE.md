# Database Schema & Queries

## Overview

The ElastiCache Monitor uses a **hybrid SQLite architecture**:

- **Main DB** (`data/redis_monitor.db`): Job metadata
- **Per-Job DBs** (`data/jobs/{job_id}.db`): Command data for each job

This enables fast queries on large datasets and easy cleanup.

---

## Schema

### Table: `monitoring_jobs` (Main DB)

| Column | Type | Description |
|--------|------|-------------|
| id | TEXT | UUID primary key |
| name | TEXT | Job name |
| replication_group_id | TEXT | AWS replication group |
| endpoint_type | TEXT | "replica" or "primary" |
| duration | INT | Monitoring duration (seconds) |
| status | TEXT | pending, running, completed, failed |
| created_at | TEXT | Job creation time (UTC) |
| started_at | TEXT | Monitoring start time |
| completed_at | TEXT | Monitoring end time |
| total_commands | INT | Total commands captured |
| error_message | TEXT | Error details if failed |

### Table: `redis_commands` (Per-Job DB)

| Column | Type | Description |
|--------|------|-------------|
| id | INT | Auto-incrementing primary key |
| job_id | TEXT | Job UUID |
| shard_name | TEXT | Shard name (e.g., "0001") |
| timestamp | REAL | Unix timestamp |
| datetime_utc | TEXT | Human-readable UTC datetime |
| client_address | TEXT | Full client address (IP:port) |
| client_ip | TEXT | Client IP only |
| command | TEXT | Redis command (GET, SET, etc.) |
| key | TEXT | The key being accessed |
| key_pattern | TEXT | Extracted pattern (e.g., "user:{ID}") |
| args | TEXT | JSON array of command arguments |
| key_size_bytes | INT | Size of key (if sampled) |

**Indexes:**
- `idx_job_shard_cmd` on (job_id, shard_name, command)
- `idx_job_pattern` on (job_id, key_pattern)

### Table: `key_size_cache` (Per-Job DB)

| Column | Type | Description |
|--------|------|-------------|
| id | INT | Primary key |
| job_id | TEXT | Job UUID |
| key | TEXT | Redis key |
| size_bytes | INT | Key size in bytes |
| sampled_at | TEXT | When sampled |

---

## Example Queries

### Via Web UI

The Web UI provides a SQL query interface at `/query`. Select a job and run queries directly.

### Via CLI

```bash
# Using sqlite3 directly on a job database
sqlite3 data/jobs/{job_id}.db

# Top commands
SELECT command, COUNT(*) as cnt 
FROM redis_commands 
GROUP BY command 
ORDER BY cnt DESC 
LIMIT 10;

# Hot shards
SELECT shard_name, COUNT(*) as commands
FROM redis_commands
GROUP BY shard_name
ORDER BY commands DESC;

# Top key patterns
SELECT key_pattern, COUNT(*) as access_count
FROM redis_commands
WHERE key_pattern IS NOT NULL
GROUP BY key_pattern
ORDER BY access_count DESC
LIMIT 20;

# Keys with sizes
SELECT key, key_size_bytes, shard_name
FROM redis_commands
WHERE key_size_bytes IS NOT NULL
ORDER BY key_size_bytes DESC
LIMIT 20;

# Commands per minute
SELECT strftime('%Y-%m-%d %H:%M', datetime_utc) as minute,
       COUNT(*) as commands
FROM redis_commands
GROUP BY minute
ORDER BY minute;
```

---

## Key Patterns

The system automatically extracts patterns from keys:

| Pattern | Matches | Example |
|---------|---------|---------|
| `{UUID}` | UUIDs | `user:550e8400-e29b-41d4-a716-446655440000` |
| `{HASH}` | MD5/SHA hashes | `cache:d41d8cd98f00b204e9800998ecf8427e` |
| `{ID}` | 6+ digit numbers | `session:1234567890` |
| `{DATE}` | YYYY-MM-DD | `logs:2024-01-15` |
| `{IP}` | IP addresses | `ratelimit:192.168.1.1` |

