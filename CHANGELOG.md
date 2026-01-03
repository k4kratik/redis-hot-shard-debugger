# Changelog

All notable changes to the Redis Hot Shard Debugger Web UI.

---

## Session: December 28, 2025

### Features Added

#### 1. **Redis Server Info via INFO Snapshot**
- Added one-time `INFO` capture at start and end of monitoring for each shard
- **Redis Version**: Captured from `INFO SERVER`, displayed as a badge on shard cards (e.g., `v7.0.7`)
- **Memory Stats**: Captured from `INFO MEMORY` at end of monitoring:
  - `used_memory`: Current memory used
  - `maxmemory`: Max configured memory (0 = no limit)
  - `used_memory_peak`: Peak memory usage
  - `used_memory_rss`: OS-level RSS memory
- Memory displayed as a progress bar with percentage, color-coded:
  - Green: < 60% usage
  - Amber: 60-80% usage
  - Red: > 80% usage
- **CPU Metrics**: Captured at start and end:
  - `used_cpu_sys`, `used_cpu_user` values
  - Calculates delta (total CPU time consumed during monitoring)
  - Color-coded amber for high CPU usage (> 5 seconds)
  - Hover tooltip shows sys vs user breakdown
- Minimal overhead: only 3 extra INFO calls per shard (server at start, cpu at start, cpu+memory at end)

#### 2. **Auto-Migration for Database Schema**
- Added automatic schema migration for both metadata DB and per-job DBs
- New columns added transparently when accessing existing databases
- Supports older jobs without breaking (missing data shows as "—")
- Migration for `monitor_shards`: redis_version, memory_used_bytes, memory_max_bytes, memory_peak_bytes, memory_rss_bytes, cpu_sys_start, cpu_user_start, cpu_sys_end, cpu_user_end, cpu_sys_delta, cpu_user_delta
- Migration for `redis_commands`: arg_shape, command_signature, is_full_scan, is_lock_op

---

## Session: December 27, 2025

### Features Added

#### 1. **Web GUI with FastAPI**
- Built a complete web-based GUI using FastAPI, Jinja2 templates, and SQLite
- Homepage for creating monitoring jobs (replication group ID, password, endpoint type, duration)
- Jobs list page showing all monitoring sessions
- Job detail page with shard status, statistics, and charts
- Analysis page with advanced query capabilities

#### 2. **Real-time Monitoring UI**
- Live countdown timer showing remaining monitoring time
- Real-time command count updates via polling
- Shard status indicators (pending, connecting, monitoring, finalizing, completed, failed)
- Automatic page refresh when job completes

#### 3. **Dynamic Timer Display**
- Timer now appears dynamically without page refresh when job starts
- Uses Alpine.js `x-show` instead of server-side conditionals
- Smooth slide-in animation when timer appears
- API endpoint returns `started_at` for accurate time calculation

#### 4. **Post-Monitoring Status Messages**
- Shows specific operation status after monitoring completes:
  - "Flushing X shard(s) to database" when shards are being saved
  - "Sampling key sizes..." during the key size sampling phase

#### 5. **Compare Jobs Feature**
- Added "Compare" tab to top navigation bar
- Checkboxes on jobs list to select 2-4 completed jobs for comparison
- Dedicated `/compare` page with:
  - Color-coded job overview cards (purple, emerald, amber, cyan)
  - Key metrics comparison table (commands, duration, commands/sec, shards, keys, patterns)
  - Diff column showing differences between jobs
  - Command distribution side-by-side bar charts
  - Top key patterns comparison
  - Shard distribution chart with all jobs overlaid
- Job selection UI when accessing Compare directly from nav

#### 6. **Instant Page Load (Performance Optimization)**
- Job detail page now loads instantly
- Heavy data (charts, command distributions, patterns) loaded asynchronously via `/api/jobs/{job_id}/stats`
- Loading skeleton with spinner shown while fetching chart data
- Alpine.js `chartManager` component handles async data loading

#### 7. **Interactive Chart Features**
- Toggle buttons for "Total", "Commands", and "Patterns" views
- Interactive legend filtering:
  - Left-click to isolate a single dataset
  - Right-click to hide/show datasets
- Hint bar below chart explaining legend interactions

#### 8. **Sortable Tables**
- Added sortable columns to analysis page tables
- Click column headers to sort ascending/descending
- Works for Key Pattern, Individual Key, Shard, Command, and Client IP views

#### 9. **Custom Autocomplete for Replication Group ID**
- Shows previously used replication group names as suggestions
- Uses HTML5 `datalist` element
- Browser autofill disabled to prevent email suggestions

#### 10. **Browser Autofill Prevention**
- Disabled browser autofill on password fields
- Uses `readonly` + `onfocus` technique
- Added data attributes to prevent password managers (1Password, LastPass, Bitwarden)

#### 11. **Enhanced Query Page**
- Job selector dropdown at top (shows job name, creation time, command count)
- "Quick Queries" section with one-click executable queries
- Copy button with green tick confirmation
- Loading animation when executing queries
- Queries automatically scoped to selected job's database

#### 12. **Re-run Job Feature**
- "Re-run" button on each job in the jobs list
- Modal prompts for password (not stored for security)
- Creates new job with same configuration

#### 13. **Key Size Display**
- Shows key sizes in Individual Keys view
- Shows average size in Key Patterns view
- Uses `MEMORY USAGE` Redis command for sampling

#### 14. **Per-Job Database Architecture**
- Migrated from single SQLite DB to hybrid architecture
- Main DB (`redis_monitor.db`) stores job metadata
- Per-job DBs (`data/jobs/{job_id}.db`) store command data
- Improves query performance for large datasets
- Migration script created to move existing data

#### 15. **Key Pattern Extraction Improvement**
- Changed numeric sequence detection from `{TIMESTAMP}` to `{ID}`
- Better reflects that numbers in keys are typically user IDs

### UI/UX Improvements

#### 16. **Clickable Job Names**
- Job names in the jobs list are now clickable links
- Navigate directly to job detail page
- Red hover color indicates clickability

#### 17. **Fixed Shard Card Layout**
- Removed `overflow-hidden` that was cutting off status badges
- Added `flex-shrink-0` and `whitespace-nowrap` to prevent badge truncation
- Hostname text properly truncated with ellipsis

#### 18. **Default Limit Change**
- Changed default limit for Individual Keys from 50 to 20
- Prevents overwhelming the UI with too much data

### Bug Fixes

#### 19. **Fixed Jinja2 `loop.parent` Error**
- Changed `loop.parent.loop.index` to `{% set job_idx = loop.index %}`
- Jinja2 doesn't support `loop.parent` syntax

#### 20. **Fixed SQLAlchemy DetachedInstanceError**
- Converted ORM objects to dictionaries before session closes
- Prevents errors when accessing attributes in templates

#### 21. **Fixed Thread Join Timeout**
- Changed `thread.join(timeout=10)` to `thread.join(timeout=duration+60)`
- Ensures monitoring threads run for full specified duration

#### 22. **Fixed Log Message Port**
- Corrected startup log from "localhost:8080" to "localhost:8099"

### API Endpoints Added

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Homepage - create new job |
| `/jobs` | GET | List all jobs |
| `/jobs/{job_id}` | GET | Job detail page |
| `/jobs/{job_id}/analysis` | GET | Analysis page |
| `/jobs/{job_id}/shards/{shard_name}` | GET | Shard detail page |
| `/jobs/{job_id}/rerun` | POST | Re-run a job |
| `/compare` | GET | Compare jobs page |
| `/query` | GET | Custom SQL query page |
| `/api/jobs/{job_id}/status` | GET | Poll job status |
| `/api/jobs/{job_id}/stats` | GET | Get chart/stats data (async) |
| `/api/jobs/{job_id}/chart-data` | GET | Get specific chart data |
| `/api/jobs/{job_id}/delete` | DELETE | Delete a job |

---

## Technical Stack

- **Backend**: FastAPI, SQLAlchemy, SQLite
- **Frontend**: Jinja2 templates, Tailwind CSS, Alpine.js, Chart.js
- **Fonts**: Plus Jakarta Sans, IBM Plex Mono
- **Icons**: Heroicons (inline SVG)

