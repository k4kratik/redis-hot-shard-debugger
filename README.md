# ElastiCache Hot Shard Debugger

Debug hot shard issues in AWS ElastiCache (Redis/Valkey) clusters with a beautiful web interface.

## Quick Start

```bash
# Install
uv pip install -e .

# Run
elasticache-web
```

Open **http://localhost:8099** and start monitoring!

---

## Features

- 🌐 **Web Interface** — Modern UI with real-time updates
- ⏱️ **Live Monitoring** — Countdown timer, per-shard status
- 📊 **Interactive Charts** — Click to filter, right-click to hide
- 🔍 **Analysis** — Sortable tables for keys, patterns, shards, commands
- 🔄 **Compare Jobs** — Side-by-side comparison of 2-4 sessions
- 💾 **SQL Queries** — Built-in editor with quick query templates

---

## Usage

### 1. Start the Server

```bash
elasticache-web              # Default port 8099
elasticache-web --port 3000  # Custom port
```

### 2. Create a Monitoring Job

1. Enter your **Replication Group ID**
2. Enter your **Redis password**
3. Set **duration** (30-300 seconds)
4. Click **Start Monitoring**

### 3. View Results

- **Dashboard** — Real-time command counts, shard status
- **Charts** — Command distribution, key patterns
- **Analysis** — Deep dive into keys and patterns
- **Compare** — Compare multiple monitoring sessions

---

## Requirements

- Python 3.12+
- AWS credentials (for endpoint auto-discovery)
- Network access to ElastiCache cluster

### Install

```bash
# Using uv (recommended)
uv pip install -e .

# Or pip
pip install -e .
```

---

## Production Safety

⚠️ **Always use replica endpoints** for monitoring in production. The `MONITOR` command can impact performance on primary nodes.

The web UI defaults to replica endpoints.

---

## AWS Permissions

```json
{
  "Effect": "Allow",
  "Action": [
    "elasticache:DescribeReplicationGroups",
    "elasticache:DescribeCacheClusters"
  ],
  "Resource": "*"
}
```

---

## Documentation

| Document | Description |
|----------|-------------|
| [CLI Reference](docs/CLI.md) | Command-line tools (for scripting) |
| [Database Schema](docs/DATABASE.md) | SQLite schema & example queries |
| [Changelog](CHANGELOG.md) | Version history |

---

## CLI (Legacy)

For scripting and automation, CLI tools are still available:

```bash
elasticache-monitor -c my-cluster -p PASSWORD -d 60
```

See [docs/CLI.md](docs/CLI.md) for full reference.

---

**Version**: 2.0.0 · **Python**: 3.12+ · **License**: MIT
