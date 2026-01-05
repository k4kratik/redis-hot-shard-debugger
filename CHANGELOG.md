# Changelog

All notable changes to the ElastiCache Hot Shard Debugger Web UI.

---

## Session: January 6, 2026

### Feature: SQL Editor with Syntax Highlighting (Ace Editor)

#### Problem
- Previous overlay-based syntax highlighting caused cursor position issues
- CodeMirror ES module loading was unreliable

#### Solution
- Integrated **Ace Editor** - a battle-tested code editor used by GitHub, Cloud9, etc.
- Single script includes that load reliably

#### Features
- **Full SQL syntax highlighting** - keywords (purple), strings (green), numbers (yellow)
- **Line numbers** in gutter
- **Proper cursor positioning** - clicking works correctly
- **Ctrl+Enter / Cmd+Enter** to run queries
- **Shift+Alt+F** to format/beautify SQL
- **Format button** - one-click SQL beautification (uppercase keywords, proper indentation)
- **Resizable editor** - drag bottom-right corner to resize (150px - 600px)
- **Dark "One Dark" theme** matching app design
- **Active line highlighting**

#### Files Changed
- `src/elasticache_monitor/web/templates/query.html`

---

### UI Consistency: SQL Query Page Layout

#### Fixed
- **Header alignment**: Restructured SQL Query page to match other pages (Timeline, Shards, etc.)
- **Breadcrumb navigation**: Added consistent breadcrumb (Jobs → [Job Name] → SQL Query)
- **Job selector position**: Moved job selector below header row for better visual hierarchy
- **Navigation buttons**: Right-aligned with consistent styling

#### Files Changed
- `src/elasticache_monitor/web/templates/query.html`

---

### Feature: Share Button on Query & Analysis Pages

#### Added
- **Share button on SQL Query page**: Allows sharing current job selection
- **Share button on Analysis page**: Allows sharing analysis view with filters
- Both buttons create short URLs with fallback to full URLs
- Hover tooltips explain the sharing feature
- "Copied!" confirmation with checkmark animation

#### Files Changed
- `src/elasticache_monitor/web/templates/query.html`
- `src/elasticache_monitor/web/templates/analysis.html`

---

### Feature: Shareable URLs & Short Links (Grafana-style)

#### Overview
Implemented a comprehensive URL state management system inspired by Grafana/Kibana. All page state is now preserved in the URL, making dashboards bookmarkable, shareable, and browser navigation-friendly.

#### Added
- **URL State Management** (`/static/js/url_state.js`): Central utility for syncing page state to/from URL
- **Short URL System**: Server-backed URL shortening for easy sharing
  - `POST /api/short-urls` - Create short URLs (with deduplication)
  - `GET /s/{id}` - Redirect to full URL (with hit tracking)
- **Share Button**: Contextual share button near chart controls with hover tooltip
- **Browser Navigation**: Back/forward buttons now work correctly with page state

#### Pages with URL State & Share Button
- **Timeline Analysis**: group_by, granularity, chart_type, shards, filters
- **Shard Distribution**: group_by, chart_type, filters
- **SQL Query**: job_id selection
- **Analysis**: current job view with filters

#### How It Works
1. **URL is the source of truth** - All state changes update the URL
2. **Reload-safe** - Refreshing preserves all filters and settings
3. **Shareable** - Copy URL directly or use Share button for short link
4. **Back/Forward** - Browser navigation works as expected

#### Database Changes
- Added `short_urls` table for storing URL mappings with hit counts

#### Files Changed
- `src/elasticache_monitor/web/static/js/url_state.js` (new file)
- `src/elasticache_monitor/web/models.py` (added `ShortUrl` model)
- `src/elasticache_monitor/web/db.py` (migration for `short_urls` table)
- `src/elasticache_monitor/web/main.py` (API endpoints + static files mount)
- `src/elasticache_monitor/web/templates/base.html` (loads url_state.js)
- `src/elasticache_monitor/web/templates/timeline.html` (URL state + Share button)
- `src/elasticache_monitor/web/templates/shard_distribution.html` (URL state + Share button + chart optimization)

---

### Critical Bug Fix: Chart.js Crash on Rapid Clicking

#### Problem
- Rapidly clicking Group By / Stack By buttons on Timeline and Shard Distribution pages caused Chart.js crashes
- Error: `Uncaught TypeError: Cannot read properties of null (reading 'getContext')`
- Also caused `RangeError: Maximum call stack size exceeded` errors

#### Root Cause
- Async race conditions where multiple fetch requests completed out of order
- Chart.js `destroy()` + `new Chart()` cycles conflicting during rapid interactions
- Data mutations during chart updates causing infinite loops

#### Solution
- **Simplified chart rendering**: Always recreate chart on data change (no in-place updates)
- **Clone data before rendering**: Use `.slice()` on arrays to prevent reference issues
- **Request ID tracking**: Discard stale async responses using `requestId` counter
- **Loading guards**: Prevent new actions while previous request is in progress
- **Disabled animations**: Set `animation: false` for stability
- **Single click handler**: Bind chart click handler only once per canvas lifetime

#### Files Changed
- `src/elasticache_monitor/web/templates/timeline.html`
- `src/elasticache_monitor/web/templates/shard_distribution.html`

### Feature: AWS CloudWatch CPU Integration

#### Added
- **AWS EngineCPUUtilization metric**: Fetches CPU utilization from CloudWatch after monitoring completes
- Shows AWS-reported CPU % alongside Redis INFO CPU metrics on shard cards
- Helps correlate Redis-reported CPU with AWS infrastructure view
- Created dedicated `cloudwatch.py` module for AWS metric fetching

#### Technical Details
- Queries `AWS/ElastiCache` namespace for `EngineCPUUtilization` metric
- Uses 1-minute granularity with ±2 minute time window buffer
- Returns both average and maximum CPU values from the monitoring period
- Gracefully handles missing data or AWS API errors

#### Files Changed
- `src/elasticache_monitor/web/cloudwatch.py` (new file)
- `src/elasticache_monitor/web/runner.py` (calls CloudWatch after monitoring)
- `src/elasticache_monitor/web/models.py` (added `aws_engine_cpu_max` column)
- `src/elasticache_monitor/web/templates/job_detail.html` (displays AWS CPU %)

### Other Recent Features & Fixes

#### New Pages
- **Shard Distribution Page** (`/jobs/{id}/shard-distribution`): Compare traffic across shards with stacked bar charts
- **About Page** (`/about`): Project info, author details, and links

#### Job Management
- **Job Cancellation**: Cancel running jobs with confirmation modal
- **Jobs Pagination**: Navigate through jobs list with page controls (min 10 per page)
- **Duplicate Job Prevention**: Compare page prevents selecting same job twice

#### UI/UX Improvements
- **Local Time Display**: All timestamps converted from UTC to user's local timezone
- **SQL Syntax Highlighting**: Prism.js integration for better SQL readability in Query page
- **Smart Filter Options**: Filter dropdowns only show relevant options based on current selections
- **Version Display**: Version shown in navbar, footer, and CLI startup

#### Rebranding
- **Redis → ElastiCache**: Renamed throughout UI to "ElastiCache Monitor"
- **Redis/Valkey**: References now say "Redis/Valkey" where appropriate
- **Database Renamed**: `redis_monitor.db` → `elasticache_monitor.db` (with backward compatibility)

#### CLI Improvements
- **Dynamic Version**: Version read from package metadata at runtime (no hardcoding)
- **Version in Startup**: Shows version when running `elasticache-monitor` CLI

---

## Session: January 3, 2026

### UI Polish & Production Readiness

#### 1. **Consistent Navigation with Icons**
- Added matching icons to all page navigation buttons (Overview, Timeline, Shards, Analyze, SQL)
- Icons match page purpose: grid for Overview, chart for Timeline, database for Shards, bars for Analyze, terminal for SQL
- Consistent styling across all job-related pages

#### 2. **Standardized Breadcrumb Navigation**
- Added proper breadcrumb navigation to Timeline and Shard Distribution pages
- Format: `Jobs → [Job Name] → [Current Page]`
- Consistent header structure with title icons across all pages

#### 3. **Mobile Responsiveness**
- Added hamburger menu for mobile devices in navbar
- Stats grids now use responsive breakpoints (`grid-cols-2 lg:grid-cols-4`)
- Navigation wraps properly on smaller screens
- Footer links responsive layout

#### 4. **Accessibility Improvements**
- Added visible focus styles for keyboard navigation (`:focus-visible`)
- Added `prefers-reduced-motion` media query for users who prefer less animation
- Proper color contrast maintained

#### 5. **Footer Enhancement**
- Added footer links to About page and GitHub
- Version number displayed in footer
- Responsive layout for mobile

#### 6. **Job ID in Jobs List**
- Shows first 8 characters of job UUID in the jobs list
- Hash icon indicator
- Full job ID shown on hover (tooltip)
- Muted styling to not compete with job name

#### 7. **Auto-Focus on Filter Search**
- Filter dropdowns now auto-focus the search input when opened
- Immediately start typing to filter options
- Works on both Timeline and Shard Distribution pages
- All dropdown filters: Shard, Command, Key Pattern, Signature

#### 8. **Compare Page Polish**
- Added breadcrumb navigation
- Title icon for visual consistency
- Responsive header layout

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
- Main DB (`elasticache_monitor.db`) stores job metadata
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

