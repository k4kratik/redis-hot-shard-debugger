"""CLI entry points for elasticache-monitor"""

import os
import sys
import time
import signal
import yaml
import subprocess
from datetime import datetime
from threading import Thread
from pathlib import Path

import click
from colorama import Fore, init
from tabulate import tabulate

from .monitor import ShardMonitor
from .endpoints import get_replica_endpoints, get_all_endpoints
from .analyzer import analyze_log_file
from .reporter import print_comparison_report, save_report, print_summary
from .database import MonitorDatabase

init(autoreset=True)


@click.command()
@click.option('--cluster-id', '-c', 
              help='ElastiCache cluster/replication group ID')
@click.option('--password', '-p', required=True, 
              help='Redis password')
@click.option('--region', '-r', default='ap-south-1', 
              help='AWS region (default: ap-south-1)')
@click.option('--profile', 
              help='AWS profile name (e.g., production)')
@click.option('--duration', '-d', default=60, type=int,
              help='Duration to monitor in seconds (default: 60)')
@click.option('--output-dir', '-o', default='./reports',
              help='Output directory for reports (default: ./reports)')
@click.option('--save-logs/--no-save-logs', default=True,
              help='Save raw monitor logs (default: yes)')
@click.option('--save-to-db', is_flag=True,
              help='Save logs to SQLite database for custom queries')
@click.option('--db-path', default='./reports/monitor_logs.db',
              help='SQLite database path (default: ./reports/monitor_logs.db)')
@click.option('--endpoints', '-e', multiple=True,
              help='Manual endpoints (format: host:port:name). Bypasses auto-discovery. Can specify multiple times.')
@click.option('--use-primary', is_flag=True,
              help='Use PRIMARY endpoints instead of replicas (⚠️  not recommended for production)')
@click.option('--estimate-bandwidth', is_flag=True,
              help='Estimate bandwidth by sampling actual key sizes (adds ~10s analysis time)')
def auto_monitor(cluster_id, password, region, profile, duration, output_dir, save_logs, save_to_db, db_path, endpoints, use_primary, estimate_bandwidth):
    """
    🤖 Automated ElastiCache Hot Shard Monitor
    
    Just provide cluster name and password - everything else is automatic!
    
    Bypass Options:
    
    \b
    --endpoints        Manual endpoints (bypasses auto-discovery)
    --use-primary      Use primary nodes (bypasses replica-only safety)
    
    Examples:
    
    \b
    # Manual endpoints (bypass auto-discovery)
    elasticache-monitor -p PASS -e host1:6379:shard1 -e host2:6379:shard2
    
    \b
    # Use primary endpoints (bypass replica-only)
    elasticache-monitor -c my-cluster -p PASS --use-primary
    """
    
    print(f"{Fore.GREEN}{'='*80}")
    print(f"{Fore.GREEN}🤖 AUTOMATED ELASTICACHE HOT SHARD MONITOR")
    print(f"{Fore.GREEN}{'='*80}\n")
    
    # Create output directory
    os.makedirs(output_dir, exist_ok=True)
    
    # Determine endpoint discovery method
    discovered_endpoints = []
    
    if endpoints:
        # Manual endpoints specified - bypass auto-discovery
        print(f"{Fore.CYAN}Using manual endpoints (bypassing auto-discovery)...\n")
        for endpoint in endpoints:
            parts = endpoint.split(':')
            if len(parts) == 3:
                host, port, name = parts
                discovered_endpoints.append({
                    'address': host,
                    'port': int(port),
                    'shard': name,
                    'role': 'manual'
                })
            else:
                print(f"{Fore.RED}Invalid endpoint format: {endpoint}")
                print(f"{Fore.YELLOW}Expected format: host:port:name")
                sys.exit(1)
    
    elif cluster_id:
        # Auto-discovery from AWS
        print(f"{Fore.CYAN}Configuration:")
        print(f"  Cluster ID: {cluster_id}")
        print(f"  Region: {region}")
        print(f"  Duration: {duration} seconds")
        print(f"  Output Dir: {output_dir}")
        
        if use_primary:
            print(f"  {Fore.RED}⚠️  WARNING: Using PRIMARY endpoints (not recommended for production!)\n")
            discovered_endpoints = get_all_endpoints(cluster_id, region, primary_only=True, profile=profile)
        else:
            print(f"  {Fore.YELLOW}⚠️  Using REPLICA endpoints (production safe)\n")
            discovered_endpoints = get_replica_endpoints(cluster_id, region, profile=profile)
    
    else:
        print(f"{Fore.RED}Error: Either --cluster-id or --endpoints must be specified!")
        print(f"{Fore.YELLOW}Examples:")
        print(f"  elasticache-monitor -c my-cluster -p PASS")
        print(f"  elasticache-monitor -p PASS -e host:6379:shard1 -e host:6379:shard2")
        sys.exit(1)
    
    if not discovered_endpoints:
        print(f"{Fore.RED}❌ No endpoints found!")
        if cluster_id:
            print(f"{Fore.YELLOW}Possible reasons:")
            print(f"  - Cluster doesn't exist or name is incorrect")
            if not use_primary:
                print(f"  - No replicas configured (try --use-primary or manual --endpoints)")
            print(f"  - AWS credentials not configured")
            print(f"\n{Fore.CYAN}Bypass options:")
            print(f"  1. Use primary: elasticache-monitor -c {cluster_id} -p PASS --use-primary")
            print(f"  2. Manual endpoints: elasticache-monitor -p PASS -e host:6379:shard1")
        sys.exit(1)
    
    role_type = "manual" if endpoints else ("primary" if use_primary else "replica")
    print(f"{Fore.GREEN}✓ Found {len(discovered_endpoints)} {role_type} endpoints:")
    for e in discovered_endpoints:
        print(f"  - {e['shard']}: {e['address']}:{e['port']}")
    print()
    
    # Initialize database session if requested
    session_id = None
    collection_time = datetime.now().isoformat()
    
    if save_to_db:
        print(f"{Fore.CYAN}💾 Initializing database: {db_path}")
        # Create database and start session in main thread
        with MonitorDatabase(db_path) as db:
            session_id = db.start_session(
                cluster_id or "manual",
                len(discovered_endpoints),
                {
                    'region': region,
                    'duration': duration,
                    'profile': profile or 'default',
                    'use_primary': use_primary
                }
            )
        print(f"{Fore.GREEN}✓ Database session #{session_id} started\n")
    
    # Create monitors (each will create its own DB connection in its thread)
    monitors = []
    for e in discovered_endpoints:
        monitor = ShardMonitor(
            e['address'],
            e['port'],
            password,
            e['shard'],
            duration,
            db_path=db_path if save_to_db else None,
            cluster_id=cluster_id or "manual",
            collection_time=collection_time
        )
        monitors.append(monitor)
    
    # Start monitoring
    print(f"{Fore.CYAN}🔍 Starting monitoring for {duration} seconds...")
    print(f"{Fore.YELLOW}   (Press Ctrl+C to stop early)\n")
    
    threads = []
    for monitor in monitors:
        thread = Thread(target=monitor.monitor)
        thread.start()
        threads.append(thread)
    
    # Signal handler
    def signal_handler(sig, frame):
        print(f"\n{Fore.YELLOW}⚠️  Stopping monitors...")
        for monitor in monitors:
            monitor.stop_event.set()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    
    # Progress indicator
    start = time.time()
    try:
        while any(t.is_alive() for t in threads):
            elapsed = int(time.time() - start)
            
            # Safety check - force stop if exceeded duration by 10 seconds
            if elapsed > duration + 10:
                print(f"\n{Fore.YELLOW}⚠️  Exceeded duration, force stopping monitors...")
                for monitor in monitors:
                    monitor.stop_event.set()
                break
            
            remaining = max(0, duration - elapsed)
            progress = min(100, int(elapsed / duration * 100))
            bar = '█' * (progress // 2) + '░' * (50 - progress // 2)
            print(f"\r{Fore.CYAN}Progress: [{bar}] {progress}% ({elapsed}/{duration}s)", 
                  end='', flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}⚠️  Interrupted by user, stopping monitors...")
        for monitor in monitors:
            monitor.stop_event.set()
    
    print(f"\n\n{Fore.GREEN}✓ Monitoring complete!\n")
    
    # Wait for all threads with timeout
    for monitor in monitors:
        monitor.stop_event.set()
    
    for thread in threads:
        thread.join(timeout=10)
        if thread.is_alive():
            print(f"{Fore.YELLOW}⚠️  Thread still running, forcing cleanup...")
    
    # Collect stats
    stats = [m.get_stats() for m in monitors]
    
    # Estimate bandwidth if requested
    if estimate_bandwidth:
        print(f"\n{Fore.CYAN}📊 Estimating bandwidth by sampling key sizes...")
        from .bandwidth import estimate_shard_bandwidth
        
        for i, monitor in enumerate(monitors):
            if monitor.error:
                continue
            
            bandwidth_data = estimate_shard_bandwidth(
                stats[i],
                monitor.host,
                monitor.port,
                password
            )
            
            # Add bandwidth data to stats
            stats[i]['bandwidth'] = bandwidth_data
        
        print(f"{Fore.GREEN}✓ Bandwidth estimation complete\n")
    
    # End database session if used
    if save_to_db and session_id:
        total_commands = sum(s['total_commands'] for s in stats)
        with MonitorDatabase(db_path) as db:
            db.end_session(session_id, duration, total_commands)
        print(f"{Fore.GREEN}✓ Database session #{session_id} completed ({total_commands} commands)")
        print(f"{Fore.CYAN}   Query with: elasticache-query --db-path {db_path}\n")
    
    # Generate reports
    print(f"{Fore.CYAN}📝 Generating reports...")
    report_file, markdown_file, json_file = save_report(stats, output_dir, cluster_id or 'manual', format='all')
    
    # Save raw logs
    if save_logs:
        log_dir = os.path.join(output_dir, 'raw_logs')
        os.makedirs(log_dir, exist_ok=True)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        for monitor in monitors:
            if monitor.monitor_lines:
                log_file = os.path.join(log_dir, f'{monitor.shard_name}_{timestamp}.log')
                with open(log_file, 'w') as f:
                    for line in monitor.monitor_lines:
                        line_str = line.decode('utf-8') if isinstance(line, bytes) else line
                        f.write(line_str + '\n')
    
    # Print summary
    print_summary(stats, cluster_id)
    
    # Report files
    print(f"\n{Fore.GREEN}{'='*80}")
    print(f"{Fore.GREEN}✓ COMPLETE!")
    print(f"{Fore.GREEN}{'='*80}\n")
    print(f"{Fore.CYAN}📁 Reports saved:")
    print(f"   Text:     {report_file}")
    print(f"   Markdown: {markdown_file}")
    print(f"   JSON:     {json_file}")
    if save_logs:
        print(f"   Logs:     {log_dir}/")
    if save_to_db:
        print(f"   Database: {db_path}")
        print(f"\n{Fore.CYAN}💡 Query database:")
        print(f"   elasticache-query --db-path {db_path}")
        print(f"   elasticache-query --db-path {db_path} --session {session_id}")
    
    print()


@click.command()
@click.option('--cluster-id', '-c', required=True, 
              help='ElastiCache cluster/replication group ID')
@click.option('--region', '-r', default='ap-south-1', 
              help='AWS region (default: ap-south-1)')
@click.option('--profile',
              help='AWS profile name (e.g., production)')
@click.option('--primary-only', '-p', is_flag=True, 
              help='Only return primary/master endpoints')
@click.option('--replica-only', is_flag=True, 
              help='Only return replica/read endpoints (recommended for production)')
@click.option('--format', '-f', type=click.Choice(['table', 'monitor-cmd', 'endpoints']), 
              default='table', help='Output format')
def get_endpoints(cluster_id, region, profile, primary_only, replica_only, format):
    """Get all shard endpoints from an ElastiCache cluster"""
    
    print(f"{Fore.CYAN}Fetching endpoints for cluster: {cluster_id} in region: {region}")
    if profile:
        print(f"{Fore.CYAN}Using AWS profile: {profile}\n")
    else:
        print()
    
    endpoints = get_all_endpoints(cluster_id, region, primary_only, replica_only, profile=profile)
    
    if not endpoints:
        print(f"{Fore.RED}No endpoints found!")
        return
    
    if primary_only and replica_only:
        print(f"{Fore.RED}Cannot use both --primary-only and --replica-only!")
        return
    
    if format == 'table':
        table_data = [[e['shard'], e['address'], e['port'], e['role']] for e in endpoints]
        print(tabulate(table_data, headers=['Shard', 'Address', 'Port', 'Role'], tablefmt='grid'))
    
    elif format == 'monitor-cmd':
        print(f"{Fore.GREEN}Use these endpoints with elasticache-monitor:\n")
        print("elasticache-monitor \\")
        print(f"    -c {cluster_id} \\")
        print(f"    -r {region} \\")
        print("    -p YOUR_PASSWORD \\")
        print("    -d 60")
    
    elif format == 'endpoints':
        for e in endpoints:
            print(f"{e['address']}:{e['port']}:{e['shard']}")


@click.command()
@click.argument('logfiles', nargs=-1, required=True, type=click.Path(exists=True))
@click.option('--compare', '-c', is_flag=True, help='Compare multiple log files')
def analyze_logs(logfiles, compare):
    """Analyze monitor log files collected from Redis/Valkey"""
    
    all_stats = {}
    
    for logfile in logfiles:
        print(f"{Fore.GREEN}Analyzing {logfile}...")
        stats = analyze_log_file(logfile)
        all_stats[logfile] = stats
        
        if not compare:
            _print_single_analysis(stats, logfile)
    
    if compare and len(all_stats) > 1:
        _print_comparison(all_stats)


def _print_single_analysis(stats, filename):
    """Print analysis for a single log file"""
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}Analysis for: {filename}")
    print(f"{Fore.CYAN}{'='*80}\n")
    
    print(f"{Fore.YELLOW}Overall Statistics:")
    print(f"  Total Commands: {stats['total_commands']:,}")
    print(f"  Duration: {stats['duration']:.2f} seconds")
    print(f"  QPS: {stats['qps']:.2f}")
    print(f"  Unique Clients: {len(stats['client_ips'])}")
    
    print(f"\n{Fore.YELLOW}Top 20 Commands:")
    cmd_data = [[cmd, count, f"{count/stats['total_commands']*100:.2f}%"] 
                for cmd, count in stats['commands_by_type'].most_common(20)]
    print(tabulate(cmd_data, headers=['Command', 'Count', '% of Total'], tablefmt='grid'))
    
    print(f"\n{Fore.YELLOW}Top 20 Key Patterns:")
    pattern_data = [[pattern, count, f"{count/stats['total_commands']*100:.2f}%"] 
                   for pattern, count in stats['key_patterns'].most_common(20)]
    print(tabulate(pattern_data, headers=['Pattern', 'Count', '% of Total'], tablefmt='grid'))


def _print_comparison(all_stats):
    """Print comparison of multiple log files"""
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}COMPARISON REPORT")
    print(f"{Fore.CYAN}{'='*80}\n")
    
    print(f"{Fore.YELLOW}Summary Comparison:")
    summary_data = []
    for filename, stats in all_stats.items():
        summary_data.append([
            Path(filename).name,
            f"{stats['total_commands']:,}",
            f"{stats['qps']:.2f}",
            f"{len(stats['client_ips'])}",
            f"{stats['duration']:.1f}s"
        ])
    print(tabulate(summary_data,
                  headers=['File', 'Commands', 'QPS', 'Unique Clients', 'Duration'],
                  tablefmt='grid'))


@click.command()
@click.option('--config', '-c', default='config.yaml',
              help='Config file path (default: config.yaml)')
@click.option('--once', is_flag=True,
              help='Run once and exit')
@click.option('--interval', '-i', type=int,
              help='Override schedule interval in seconds')
def scheduled_monitor(config, once, interval):
    """Scheduled ElastiCache monitoring with config file"""
    
    print(f"{Fore.GREEN}{'='*80}")
    print(f"{Fore.GREEN}📅 SCHEDULED ELASTICACHE MONITOR")
    print(f"{Fore.GREEN}{'='*80}\n")
    
    # Load configuration
    print(f"{Fore.CYAN}📄 Loading configuration from: {config}")
    cfg = _load_config(config)
    print(f"{Fore.GREEN}✓ Configuration loaded\n")
    
    if once:
        print(f"{Fore.CYAN}Running in single-shot mode...\n")
        success = _run_monitoring(cfg)
        sys.exit(0 if success else 1)
    
    # Determine interval
    run_interval = interval or 3600
    
    print(f"{Fore.CYAN}⏰ Running monitoring every {run_interval} seconds")
    print(f"{Fore.CYAN}   (Press Ctrl+C to stop)\n")
    
    run_count = 0
    try:
        while True:
            run_count += 1
            print(f"{Fore.GREEN}{'='*80}")
            print(f"{Fore.GREEN}Run #{run_count} - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{Fore.GREEN}{'='*80}\n")
            
            _run_monitoring(cfg)
            
            print(f"\n{Fore.CYAN}⏳ Next run in {run_interval} seconds...\n")
            time.sleep(run_interval)
            
    except KeyboardInterrupt:
        print(f"\n\n{Fore.YELLOW}⚠️  Stopped by user")
        print(f"{Fore.CYAN}Total runs completed: {run_count}")


def _load_config(config_file):
    """Load configuration from YAML file"""
    if not os.path.exists(config_file):
        print(f"{Fore.RED}❌ Config file not found: {config_file}")
        print(f"{Fore.YELLOW}💡 Copy config.yaml.example to config.yaml and edit it")
        sys.exit(1)
    
    with open(config_file, 'r') as f:
        config = yaml.safe_load(f)
    
    # Expand environment variables
    if 'redis' in config and 'password' in config['redis']:
        password = config['redis']['password']
        if password.startswith('${') and password.endswith('}'):
            env_var = password[2:-1]
            config['redis']['password'] = os.getenv(env_var, '')
            if not config['redis']['password']:
                print(f"{Fore.RED}❌ Environment variable not set: {env_var}")
                sys.exit(1)
    
    return config


def _run_monitoring(config):
    """Run auto_monitor with config settings"""
    cluster = config.get('cluster', {})
    redis_config = config.get('redis', {})
    monitoring = config.get('monitoring', {})
    output = config.get('output', {})
    
    # Call auto_monitor programmatically
    from click.testing import CliRunner
    runner = CliRunner()
    result = runner.invoke(auto_monitor, [
        '-c', cluster.get('id', 'unknown'),
        '-p', redis_config.get('password', ''),
        '-r', cluster.get('region', 'ap-south-1'),
        '-d', str(monitoring.get('duration', 60)),
        '-o', output.get('directory', './reports')
    ])
    
    return result.exit_code == 0


@click.command()
@click.option('--host', '-h', default='0.0.0.0',
              help='Host to bind to (default: 0.0.0.0)')
@click.option('--port', '-p', default=8080, type=int,
              help='Port to listen on (default: 8080)')
@click.option('--reload', is_flag=True,
              help='Enable auto-reload for development')
def web_server(host, port, reload):
    """
    🌐 Start the Web UI for Redis Monitor
    
    Launch a browser-based interface for monitoring and analyzing
    Redis/ElastiCache clusters.
    
    Examples:
    
    \b
    # Start on default port 8080
    elasticache-web
    
    \b
    # Start on custom port with auto-reload
    elasticache-web -p 3000 --reload
    """
    import uvicorn
    
    print(f"{Fore.GREEN}{'='*80}")
    print(f"{Fore.GREEN}🌐 REDIS HOT SHARD DEBUGGER - WEB UI")
    print(f"{Fore.GREEN}{'='*80}\n")
    
    print(f"{Fore.CYAN}Starting web server...")
    print(f"  Host: {host}")
    print(f"  Port: {port}")
    print(f"  URL:  {Fore.GREEN}http://localhost:{port}")
    print()
    
    uvicorn.run(
        "elasticache_monitor.web:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )


@click.command()
@click.option('--db-path', default='./reports/monitor_logs.db',
              help='Path to SQLite database (default: ./reports/monitor_logs.db)')
@click.option('--session', '-s', type=int,
              help='Filter by session ID')
@click.option('--cluster', '-c',
              help='Filter by cluster ID')
@click.option('--shard',
              help='Filter by shard name')
@click.option('--command', '-cmd',
              help='Filter by command type (e.g., GET, SET)')
@click.option('--pattern', '-k',
              help='Filter by key pattern')
@click.option('--limit', '-l', default=100, type=int,
              help='Limit number of results (default: 100)')
@click.option('--stats', is_flag=True,
              help='Show statistics instead of raw logs')
@click.option('--sql',
              help='Execute custom SQL query')
def query_db(db_path, session, cluster, shard, command, pattern, limit, stats, sql):
    """
    🔍 Query Monitor Database
    
    Query and analyze stored monitor logs from SQLite database.
    
    Examples:
    
    \b
    # Show statistics for all data
    elasticache-query --db-path ./reports/monitor_logs.db --stats
    
    \b
    # Show stats for specific session
    elasticache-query --session 1 --stats
    
    \b
    # Find all GET commands on shard 0001
    elasticache-query --shard 0001 --command GET --limit 50
    
    \b
    # Find keys matching pattern
    elasticache-query --pattern "ratelimit:*" --limit 20
    
    \b
    # Custom SQL query
    elasticache-query --sql "SELECT command, COUNT(*) as cnt FROM monitor_logs GROUP BY command ORDER BY cnt DESC"
    
    \b
    # Show all sessions
    elasticache-query --sql "SELECT * FROM monitoring_sessions"
    """
    
    from pathlib import Path
    
    if not Path(db_path).exists():
        print(f"{Fore.RED}❌ Database not found: {db_path}")
        print(f"{Fore.YELLOW}Have you run monitoring with --save-to-db?")
        sys.exit(1)
    
    print(f"{Fore.GREEN}{'='*80}")
    print(f"{Fore.GREEN}🔍 ELASTICACHE MONITOR DATABASE QUERY")
    print(f"{Fore.GREEN}{'='*80}\n")
    print(f"{Fore.CYAN}Database: {db_path}\n")
    
    with MonitorDatabase(db_path) as db:
        # Custom SQL query
        if sql:
            print(f"{Fore.CYAN}Executing SQL: {sql}\n")
            try:
                results = db.query(sql)
                if results:
                    # Convert to dict for tabulate
                    headers = results[0].keys()
                    rows = [tuple(row[key] for key in headers) for row in results]
                    print(tabulate(rows, headers=headers, tablefmt='grid'))
                    print(f"\n{Fore.GREEN}✓ {len(results)} rows returned")
                else:
                    print(f"{Fore.YELLOW}No results")
            except Exception as e:
                print(f"{Fore.RED}❌ SQL Error: {e}")
            return
        
        # Show statistics
        if stats:
            stats_data = db.get_stats(cluster_id=cluster, session_id=session)
            
            print(f"{Fore.CYAN}{'='*80}")
            print(f"{Fore.CYAN}📊 STATISTICS")
            print(f"{Fore.CYAN}{'='*80}\n")
            
            print(f"{Fore.GREEN}Total Commands: {stats_data['total_commands']:,}\n")
            
            # Commands by shard
            if stats_data['commands_by_shard']:
                print(f"{Fore.CYAN}Commands by Shard:")
                shard_data = sorted(stats_data['commands_by_shard'].items(), 
                                   key=lambda x: x[1], reverse=True)
                print(tabulate(shard_data, headers=['Shard', 'Count'], tablefmt='simple'))
                print()
            
            # Top commands
            if stats_data['top_commands']:
                print(f"{Fore.CYAN}Top Commands:")
                cmd_data = sorted(stats_data['top_commands'].items(), 
                                 key=lambda x: x[1], reverse=True)
                print(tabulate(cmd_data, headers=['Command', 'Count'], tablefmt='simple'))
                print()
            
            # Top key patterns
            if stats_data['top_key_patterns']:
                print(f"{Fore.CYAN}Top Key Patterns:")
                pattern_data = sorted(stats_data['top_key_patterns'].items(), 
                                    key=lambda x: x[1], reverse=True)
                print(tabulate(pattern_data, headers=['Pattern', 'Count'], tablefmt='simple'))
                print()
            
            return
        
        # Build query based on filters
        where_clauses = []
        params = []
        
        if session:
            # Get session time range
            session_data = db.query(
                "SELECT start_time, end_time FROM monitoring_sessions WHERE id = ?",
                (session,)
            )
            if not session_data:
                print(f"{Fore.RED}❌ Session {session} not found")
                return
            where_clauses.append("collection_time >= ? AND collection_time <= ?")
            params.extend([session_data[0]['start_time'], session_data[0]['end_time']])
        
        if cluster:
            where_clauses.append("cluster_id = ?")
            params.append(cluster)
        
        if shard:
            where_clauses.append("shard_name = ?")
            params.append(shard)
        
        if command:
            where_clauses.append("command = ?")
            params.append(command.upper())
        
        if pattern:
            where_clauses.append("key_pattern LIKE ?")
            params.append(f"%{pattern}%")
        
        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        query_sql = f"""
            SELECT datetime_utc, shard_name, client_ip, command, key, key_pattern
            FROM monitor_logs
            WHERE {where_sql}
            ORDER BY timestamp DESC
            LIMIT {limit}
        """
        
        print(f"{Fore.CYAN}Query filters:")
        if session:
            print(f"  Session: {session}")
        if cluster:
            print(f"  Cluster: {cluster}")
        if shard:
            print(f"  Shard: {shard}")
        if command:
            print(f"  Command: {command}")
        if pattern:
            print(f"  Pattern: {pattern}")
        print()
        
        results = db.query(query_sql, tuple(params))
        
        if results:
            # Format for display
            headers = ['Time', 'Shard', 'Client', 'Command', 'Key', 'Pattern']
            rows = []
            for row in results:
                # Truncate long keys
                key_display = (row['key'][:50] + '...') if row['key'] and len(row['key']) > 50 else row['key']
                rows.append([
                    row['datetime_utc'][:19],  # Remove microseconds
                    row['shard_name'],
                    row['client_ip'] or 'N/A',
                    row['command'],
                    key_display or 'N/A',
                    row['key_pattern'] or 'N/A'
                ])
            
            print(tabulate(rows, headers=headers, tablefmt='grid'))
            print(f"\n{Fore.GREEN}✓ Showing {len(results)} results (limit: {limit})")
        else:
            print(f"{Fore.YELLOW}No results found")


if __name__ == '__main__':
    auto_monitor()

