"""Report generation and display"""

import os
import json
from datetime import datetime
from tabulate import tabulate
from colorama import Fore


def print_comparison_report(monitors):
    """Print comprehensive comparison report"""
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}ELASTICACHE SHARD ANALYSIS REPORT")
    print(f"{Fore.CYAN}{'='*80}\n")
    
    stats = [m.get_stats() for m in monitors]
    
    # Overall summary
    print(f"{Fore.YELLOW}Overall Summary:")
    summary_data = []
    for s in stats:
        if s.get('error'):
            summary_data.append([s['shard_name'], 'ERROR', s['error'][:50], '-'])
        else:
            summary_data.append([
                s['shard_name'],
                f"{s['total_commands']:,}",
                f"{s['qps']:.2f}",
                f"{s['duration']:.1f}s"
            ])
    
    print(tabulate(summary_data, 
                   headers=['Shard', 'Total Commands', 'QPS', 'Duration'],
                   tablefmt='grid'))
    
    # Hot shard detection
    print(f"\n{Fore.YELLOW}Hot Shard Analysis:")
    valid_stats = [s for s in stats if not s.get('error')]
    
    if len(valid_stats) == 1:
        # Single shard - no comparison possible
        s = valid_stats[0]
        print(f"\n{Fore.CYAN}ℹ️  Only one shard found - no comparison available")
        print(f"   Shard: {s['shard_name']}")
        print(f"   Commands: {s['total_commands']:,}")
        print(f"   QPS: {s['qps']:.2f}")
        print(f"\n{Fore.YELLOW}💡 Note: Hot shard detection requires multiple shards for comparison.")
    else:
        # Multiple shards - perform comparison
        total_commands = sum(s['total_commands'] for s in valid_stats)
        avg_commands = total_commands / len(valid_stats) if valid_stats else 0
        
        hot_shards = []
        for s in stats:
            if s.get('error'):
                continue
            deviation = ((s['total_commands'] - avg_commands) / avg_commands * 100) if avg_commands > 0 else 0
            status = ""
            if deviation > 50:
                status = f"{Fore.RED}🔥 VERY HOT"
            elif deviation > 25:
                status = f"{Fore.YELLOW}⚠️  HOT"
            elif deviation < -25:
                status = f"{Fore.BLUE}❄️  COLD"
            else:
                status = f"{Fore.GREEN}✓ NORMAL"
            
            hot_shards.append([
                s['shard_name'],
                f"{s['total_commands']:,}",
                f"{deviation:+.1f}%",
                status
            ])
        
        print(tabulate(hot_shards,
                       headers=['Shard', 'Commands', 'Deviation from Avg', 'Status'],
                       tablefmt='grid'))
    
    # Command distribution per shard
    print(f"\n{Fore.YELLOW}Top Commands per Shard:")
    for s in stats:
        if s.get('error'):
            continue
        print(f"\n{Fore.CYAN}{s['shard_name']}:")
        cmd_data = [[cmd, count, f"{count/s['total_commands']*100:.1f}%"] 
                    for cmd, count in list(s['commands_by_type'].items())[:10]]
        if cmd_data:
            print(tabulate(cmd_data, headers=['Command', 'Count', '% of Total'], tablefmt='simple'))
    
    # Key pattern analysis
    print(f"\n{Fore.YELLOW}Top Key Patterns per Shard:")
    for s in stats:
        if s.get('error'):
            continue
        print(f"\n{Fore.CYAN}{s['shard_name']}:")
        pattern_data = [[pattern, count, f"{count/s['total_commands']*100:.1f}%"] 
                       for pattern, count in list(s['top_key_patterns'].items())[:10]]
        if pattern_data:
            print(tabulate(pattern_data, headers=['Pattern', 'Count', '% of Total'], tablefmt='simple'))
    
    # Top specific keys (potential hot keys)
    print(f"\n{Fore.YELLOW}Hot Keys per Shard (Top 10):")
    for s in stats:
        if s.get('error'):
            continue
        print(f"\n{Fore.CYAN}{s['shard_name']}:")
        key_data = [[key[:80], count] for key, count in list(s['top_keys'].items())[:10]]
        if key_data:
            print(tabulate(key_data, headers=['Key', 'Access Count'], tablefmt='simple'))
    
    # Client distribution
    print(f"\n{Fore.YELLOW}Client Distribution per Shard:")
    for s in stats:
        if s.get('error'):
            continue
        print(f"\n{Fore.CYAN}{s['shard_name']}: {s['unique_clients']} unique clients")
        client_data = [[ip, count] for ip, count in list(s['top_clients'].items())[:5]]
        if client_data:
            print(tabulate(client_data, headers=['Client IP', 'Requests'], tablefmt='simple'))
    
    print(f"\n{Fore.CYAN}{'='*80}\n")


def save_report(stats, output_dir, cluster_id, format='all'):
    """Save detailed report to file
    
    Args:
        stats: Statistics from monitors
        output_dir: Output directory
        cluster_id: Cluster ID
        format: 'text', 'markdown', 'json', or 'all' (default)
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    report_file = os.path.join(output_dir, f'report_{cluster_id}_{timestamp}.txt')
    markdown_file = os.path.join(output_dir, f'report_{cluster_id}_{timestamp}.md')
    json_file = os.path.join(output_dir, f'data_{cluster_id}_{timestamp}.json')
    
    # Save JSON data
    if format in ('json', 'all'):
        with open(json_file, 'w') as f:
            json.dump(stats, f, indent=2)
    
    # Save text report
    if format in ('text', 'all'):
        _save_text_report(stats, report_file, cluster_id)
    
    # Save markdown report
    if format in ('markdown', 'all'):
        _save_markdown_report(stats, markdown_file, cluster_id)
    
    return report_file, markdown_file, json_file


def _save_text_report(stats, report_file, cluster_id):
    """Save text format report"""
    with open(report_file, 'w') as f:
        f.write("="*80 + "\n")
        f.write(f"ELASTICACHE HOT SHARD ANALYSIS REPORT\n")
        f.write(f"Cluster: {cluster_id}\n")
        f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write("="*80 + "\n\n")
        
        # Overall summary
        f.write("OVERALL SUMMARY\n")
        f.write("-" * 80 + "\n")
        for s in stats:
            if s.get('error'):
                f.write(f"Shard: {s['shard_name']} - ERROR: {s['error']}\n")
            else:
                f.write(f"Shard: {s['shard_name']}\n")
                f.write(f"  Total Commands: {s['total_commands']:,}\n")
                f.write(f"  QPS: {s['qps']:.2f}\n")
                f.write(f"  Duration: {s['duration']:.1f}s\n")
                f.write(f"  Unique Clients: {s['unique_clients']}\n")
        f.write("\n")
        
        # Hot shard analysis
        f.write("HOT SHARD ANALYSIS\n")
        f.write("-" * 80 + "\n")
        valid_stats = [s for s in stats if not s.get('error')]
        total_commands = sum(s['total_commands'] for s in valid_stats)
        avg_commands = total_commands / len(valid_stats) if valid_stats else 0
        
        for s in stats:
            if s.get('error'):
                continue
            deviation = ((s['total_commands'] - avg_commands) / avg_commands * 100) if avg_commands > 0 else 0
            status = "VERY HOT" if deviation > 50 else "HOT" if deviation > 25 else "COLD" if deviation < -25 else "NORMAL"
            f.write(f"{s['shard_name']}: {s['total_commands']:,} commands ({deviation:+.1f}% from avg) - {status}\n")
        f.write("\n")
        
        # Key patterns per shard
        f.write("TOP KEY PATTERNS PER SHARD\n")
        f.write("-" * 80 + "\n")
        for s in stats:
            if s.get('error'):
                continue
            f.write(f"\n{s['shard_name']}:\n")
            for pattern, count in list(s['top_key_patterns'].items())[:10]:
                pct = count / s['total_commands'] * 100 if s['total_commands'] > 0 else 0
                f.write(f"  {pattern}: {count:,} ({pct:.1f}%)\n")
        f.write("\n")
        
        # Hot keys
        f.write("HOT KEYS PER SHARD\n")
        f.write("-" * 80 + "\n")
        for s in stats:
            if s.get('error'):
                continue
            f.write(f"\n{s['shard_name']}:\n")
            for key, count in list(s['top_keys'].items())[:15]:
                f.write(f"  {key[:100]}: {count:,} accesses\n")
        f.write("\n")
        
        # Command distribution
        f.write("COMMAND DISTRIBUTION PER SHARD\n")
        f.write("-" * 80 + "\n")
        for s in stats:
            if s.get('error'):
                continue
            f.write(f"\n{s['shard_name']}:\n")
            for cmd, count in list(s['commands_by_type'].items())[:10]:
                pct = count / s['total_commands'] * 100 if s['total_commands'] > 0 else 0
                f.write(f"  {cmd}: {count:,} ({pct:.1f}%)\n")


def _save_markdown_report(stats, markdown_file, cluster_id):
    """Save markdown format report"""
    with open(markdown_file, 'w') as f:
        f.write(f"# ElastiCache Hot Shard Analysis Report\n\n")
        f.write(f"**Cluster:** `{cluster_id}`  \n")
        f.write(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  \n\n")
        
        f.write("---\n\n")
        
        # Overall summary
        f.write("## Overall Summary\n\n")
        f.write("| Shard | Total Commands | QPS | Duration | Unique Clients |\n")
        f.write("|-------|----------------|-----|----------|----------------|\n")
        for s in stats:
            if s.get('error'):
                f.write(f"| {s['shard_name']} | ERROR | - | - | {s['error'][:30]} |\n")
            else:
                f.write(f"| {s['shard_name']} | {s['total_commands']:,} | {s['qps']:.2f} | {s['duration']:.1f}s | {s['unique_clients']} |\n")
        f.write("\n")
        
        # Hot shard analysis
        f.write("## Hot Shard Analysis\n\n")
        valid_stats = [s for s in stats if not s.get('error')]
        
        if len(valid_stats) == 1:
            f.write("> ℹ️ **Single shard cluster** - no comparison possible\n\n")
            s = valid_stats[0]
            f.write(f"- **Shard:** {s['shard_name']}\n")
            f.write(f"- **Commands:** {s['total_commands']:,}\n")
            f.write(f"- **QPS:** {s['qps']:.2f}\n\n")
            f.write("💡 *Focus on key pattern and command distribution below.*\n\n")
        else:
            total_commands = sum(s['total_commands'] for s in valid_stats)
            avg_commands = total_commands / len(valid_stats) if valid_stats else 0
            
            f.write("| Shard | Commands | Deviation from Avg | Status |\n")
            f.write("|-------|----------|-------------------|--------|\n")
            
            for s in stats:
                if s.get('error'):
                    continue
                deviation = ((s['total_commands'] - avg_commands) / avg_commands * 100) if avg_commands > 0 else 0
                
                if deviation > 50:
                    status = "🔥 **VERY HOT**"
                elif deviation > 25:
                    status = "⚠️ **HOT**"
                elif deviation < -25:
                    status = "❄️ **COLD**"
                else:
                    status = "✅ NORMAL"
                
                f.write(f"| {s['shard_name']} | {s['total_commands']:,} | {deviation:+.1f}% | {status} |\n")
            f.write("\n")
        
        # Key patterns per shard
        f.write("## Top Key Patterns Per Shard\n\n")
        for s in stats:
            if s.get('error'):
                continue
            f.write(f"### {s['shard_name']}\n\n")
            f.write("| Pattern | Count | % of Total |\n")
            f.write("|---------|-------|------------|\n")
            for pattern, count in list(s['top_key_patterns'].items())[:10]:
                pct = count / s['total_commands'] * 100 if s['total_commands'] > 0 else 0
                f.write(f"| `{pattern}` | {count:,} | {pct:.1f}% |\n")
            f.write("\n")
        
        # Hot keys
        f.write("## Hot Keys Per Shard\n\n")
        for s in stats:
            if s.get('error'):
                continue
            f.write(f"### {s['shard_name']} - Top 15 Keys\n\n")
            f.write("| Key | Access Count |\n")
            f.write("|-----|-------------|\n")
            for key, count in list(s['top_keys'].items())[:15]:
                # Escape pipe characters in keys for markdown
                escaped_key = key[:80].replace('|', '\\|')
                f.write(f"| `{escaped_key}` | {count:,} |\n")
            f.write("\n")
        
        # Command distribution
        f.write("## Command Distribution Per Shard\n\n")
        for s in stats:
            if s.get('error'):
                continue
            f.write(f"### {s['shard_name']}\n\n")
            f.write("| Command | Count | % of Total |\n")
            f.write("|---------|-------|------------|\n")
            for cmd, count in list(s['commands_by_type'].items())[:10]:
                pct = count / s['total_commands'] * 100 if s['total_commands'] > 0 else 0
                f.write(f"| `{cmd}` | {count:,} | {pct:.1f}% |\n")
            f.write("\n")
        
        # Client analysis
        f.write("## Client Distribution\n\n")
        for s in stats:
            if s.get('error'):
                continue
            f.write(f"### {s['shard_name']}\n\n")
            f.write(f"**Total Unique Clients:** {s['unique_clients']}\n\n")
            f.write("| Client IP | Requests | % of Total |\n")
            f.write("|-----------|----------|------------|\n")
            for ip, count in list(s['top_clients'].items())[:10]:
                pct = count / s['total_commands'] * 100 if s['total_commands'] > 0 else 0
                f.write(f"| `{ip}` | {count:,} | {pct:.1f}% |\n")
            f.write("\n")
        
        # Recommendations
        f.write("## Recommendations\n\n")
        
        # Check for hot shards
        if len(valid_stats) > 1:
            hot_shards = []
            total_commands = sum(s['total_commands'] for s in valid_stats)
            avg_commands = total_commands / len(valid_stats)
            
            for s in valid_stats:
                deviation = ((s['total_commands'] - avg_commands) / avg_commands * 100)
                if deviation > 25:
                    hot_shards.append(s['shard_name'])
            
            if hot_shards:
                f.write("### 🔥 Hot Shard Issues Detected\n\n")
                f.write(f"Shards with high load: {', '.join(f'`{s}`' for s in hot_shards)}\n\n")
                f.write("**Actions:**\n")
                f.write("1. Review key distribution patterns\n")
                f.write("2. Check if hash tags `{...}` are forcing keys to specific shards\n")
                f.write("3. Consider resharding if persistent\n")
                f.write("4. Implement client-side caching for hot keys\n\n")
        
        # Check for hot keys
        max_key_accesses = 0
        for s in valid_stats:
            if s['top_keys']:
                max_key_accesses = max(max_key_accesses, max(s['top_keys'].values()))
        
        if max_key_accesses > 1000:
            f.write("### 🔑 Hot Keys Detected\n\n")
            f.write(f"Keys with >{max_key_accesses:,} accesses detected.\n\n")
            f.write("**Actions:**\n")
            f.write("1. Implement client-side caching\n")
            f.write("2. Use local cache with TTL\n")
            f.write("3. Consider cache-aside pattern\n")
            f.write("4. Review key design\n\n")
        
        f.write("---\n\n")
        f.write("*Report generated by ElastiCache Hot Shard Monitor*\n")


def print_summary(stats, cluster_id):
    """Print quick summary to console"""
    print(f"\n{Fore.CYAN}{'='*80}")
    print(f"{Fore.CYAN}ANALYSIS COMPLETE - {cluster_id}")
    print(f"{Fore.CYAN}{'='*80}\n")
    
    # Quick summary
    print(f"{Fore.YELLOW}📊 Overall Summary:")
    summary_data = []
    for s in stats:
        if s.get('error'):
            summary_data.append([s['shard_name'], 'ERROR', s['error'][:50]])
        else:
            summary_data.append([
                s['shard_name'],
                f"{s['total_commands']:,}",
                f"{s['qps']:.2f}",
                f"{s['duration']:.1f}s"
            ])
    
    print(tabulate(summary_data, 
                   headers=['Shard', 'Commands', 'QPS', 'Duration'],
                   tablefmt='grid'))
    
    # Hot shard detection
    print(f"\n{Fore.YELLOW}🔥 Hot Shard Detection:")
    valid_stats = [s for s in stats if not s.get('error')]
    
    if len(valid_stats) == 1:
        # Single shard - show info without comparison
        s = valid_stats[0]
        print(f"\n{Fore.CYAN}ℹ️  Single shard cluster - no comparison possible")
        single_data = [[
            s['shard_name'],
            f"{s['total_commands']:,}",
            "N/A",
            f"{Fore.CYAN}✓ SINGLE SHARD"
        ]]
        print(tabulate(single_data,
                       headers=['Shard', 'Commands', 'Deviation', 'Status'],
                       tablefmt='grid'))
        print(f"\n{Fore.YELLOW}💡 Note: Hot shard analysis requires multiple shards.")
        print(f"   Focus on key pattern and command distribution below.")
    else:
        # Multiple shards - perform comparison
        total_commands = sum(s['total_commands'] for s in valid_stats)
        avg_commands = total_commands / len(valid_stats) if valid_stats else 0
        
        hot_shards = []
        for s in stats:
            if s.get('error'):
                continue
            deviation = ((s['total_commands'] - avg_commands) / avg_commands * 100) if avg_commands > 0 else 0
            status = ""
            if deviation > 50:
                status = f"{Fore.RED}🔥 VERY HOT"
            elif deviation > 25:
                status = f"{Fore.YELLOW}⚠️  HOT"
            elif deviation < -25:
                status = f"{Fore.BLUE}❄️  COLD"
            else:
                status = f"{Fore.GREEN}✓ NORMAL"
            
            hot_shards.append([
                s['shard_name'],
                f"{s['total_commands']:,}",
                f"{deviation:+.1f}%",
                status
            ])
        
        print(tabulate(hot_shards,
                       headers=['Shard', 'Commands', 'Deviation', 'Status'],
                       tablefmt='grid'))
    
    # Bandwidth analysis if available
    has_bandwidth = any('bandwidth' in s for s in valid_stats)
    if has_bandwidth:
        print(f"\n{Fore.YELLOW}📊 Estimated Bandwidth Analysis:")
        
        bandwidth_data = []
        total_bandwidth = 0
        
        for s in valid_stats:
            if 'bandwidth' in s and not s['bandwidth'].get('error'):
                bw = s['bandwidth']
                est_mb = bw.get('estimated_mb', 0)
                total_bandwidth += est_mb
                commands = s['total_commands']
                kb_per_cmd = (est_mb * 1024 / commands) if commands > 0 else 0
                
                bandwidth_data.append([
                    s['shard_name'],
                    f"{s['total_commands']:,}",
                    f"{est_mb:.2f} MB",
                    f"{kb_per_cmd:.1f} KB"
                ])
        
        if bandwidth_data:
            print(tabulate(bandwidth_data,
                          headers=['Shard', 'Commands', 'Est. Bandwidth', 'KB/Command'],
                          tablefmt='grid'))
            
            # Show hot bandwidth shards
            if len(bandwidth_data) > 1:
                avg_mb = total_bandwidth / len(bandwidth_data)
                print(f"\n{Fore.CYAN}   Average bandwidth: {avg_mb:.2f} MB")
                
                # Find hot bandwidth shards
                for s in valid_stats:
                    if 'bandwidth' in s and not s['bandwidth'].get('error'):
                        est_mb = s['bandwidth'].get('estimated_mb', 0)
                        if est_mb > avg_mb * 1.5:
                            print(f"{Fore.RED}   ⚠️  {s['shard_name']} has {(est_mb/avg_mb-1)*100:.0f}% more bandwidth than average!")
        
        # Show top bandwidth consumers
        print(f"\n{Fore.YELLOW}🔥 Top Bandwidth Consumers:")
        
        all_patterns = []
        for s in valid_stats:
            if 'bandwidth' in s and 'pattern_bandwidth' in s['bandwidth']:
                for pattern, data in s['bandwidth']['pattern_bandwidth'].items():
                    est_mb = data['estimated_bytes'] / 1024 / 1024
                    if est_mb > 0.1:  # Only show patterns > 100KB
                        all_patterns.append([
                            s['shard_name'],
                            pattern[:50],
                            data['access_count'],
                            f"{data['avg_size']/1024:.1f} KB",
                            f"{est_mb:.2f} MB"
                        ])
        
        if all_patterns:
            # Sort by estimated MB, descending
            all_patterns.sort(key=lambda x: float(x[4].split()[0]), reverse=True)
            # Show top 15
            print(tabulate(all_patterns[:15],
                          headers=['Shard', 'Key Pattern', 'Accesses', 'Avg Size', 'Est. Total'],
                          tablefmt='grid'))

