#!/usr/bin/env python3
"""
Generate blog-ready analysis and insights from benchmark results.

Usage:
    pipenv run python scripts/analyze.py
"""

import json
import os
import glob
from collections import defaultdict
from statistics import mean, median

def load_results(results_dir="results"):
    """Load all JSON results files."""
    results = []
    pattern = os.path.join(results_dir, "*.json")
    for filepath in glob.glob(pattern):
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
                results.append(data)
        except Exception as e:
            print(f"Warning: Failed to load {filepath}: {e}")
    return results

def group_by_config(results):
    """Group results by language, threads, and distribution."""
    grouped = defaultdict(lambda: defaultdict(list))
    for r in results:
        lang = r['config']['language']
        threads = r['config']['threads']
        dist = r['config']['dist']
        grouped[lang][(threads, dist)].append(r)
    return grouped

def calculate_speedup(rust_ops, go_ops):
    """Calculate speedup factor."""
    if go_ops == 0:
        return float('inf')
    return rust_ops / go_ops

def analyze_throughput(grouped):
    """Analyze throughput differences."""
    print("\n" + "="*80)
    print("THROUGHPUT ANALYSIS")
    print("="*80)
    
    for config_key in sorted(set(k for lang_data in grouped.values() for k in lang_data.keys())):
        threads, dist = config_key
        rust_runs = grouped.get('rust', {}).get(config_key, [])
        go_runs = grouped.get('go', {}).get(config_key, [])
        
        if not rust_runs or not go_runs:
            continue
        
        rust_avg = mean([r['metrics']['ops_per_sec'] for r in rust_runs])
        go_avg = mean([r['metrics']['ops_per_sec'] for r in go_runs])
        speedup = calculate_speedup(rust_avg, go_avg)
        
        print(f"\nThreads: {threads}, Distribution: {dist}")
        print(f"  Rust: {rust_avg:,.0f} ops/sec")
        print(f"  Go:   {go_avg:,.0f} ops/sec")
        print(f"  Speedup: {speedup:.2f}x")
        
        # Read/write breakdown if available
        if rust_runs[0]['metrics'].get('reads_per_sec'):
            rust_reads = mean([r['metrics']['reads_per_sec'] for r in rust_runs])
            rust_writes = mean([r['metrics']['writes_per_sec'] for r in rust_runs])
            go_reads = mean([r['metrics']['reads_per_sec'] for r in go_runs])
            go_writes = mean([r['metrics']['writes_per_sec'] for r in go_runs])
            
            read_speedup = calculate_speedup(rust_reads, go_reads)
            write_speedup = calculate_speedup(rust_writes, go_writes)
            
            print(f"  Reads:  Rust {rust_reads:,.0f} vs Go {go_reads:,.0f} ({read_speedup:.2f}x)")
            print(f"  Writes: Rust {rust_writes:,.0f} vs Go {go_writes:,.0f} ({write_speedup:.2f}x)")

def analyze_latency(grouped):
    """Analyze latency differences."""
    print("\n" + "="*80)
    print("LATENCY ANALYSIS")
    print("="*80)
    
    percentiles = ['p50', 'p95', 'p99']
    
    for config_key in sorted(set(k for lang_data in grouped.values() for k in lang_data.keys())):
        threads, dist = config_key
        rust_runs = grouped.get('rust', {}).get(config_key, [])
        go_runs = grouped.get('go', {}).get(config_key, [])
        
        if not rust_runs or not go_runs:
            continue
        
        print(f"\nThreads: {threads}, Distribution: {dist}")
        
        for p in percentiles:
            key = f'latency_us_{p}'
            rust_vals = [r['metrics'][key] for r in rust_runs]
            go_vals = [r['metrics'][key] for r in go_runs]
            
            rust_avg = mean(rust_vals)
            go_avg = mean(go_vals)
            
            if rust_avg > 0 and go_avg > 0:
                ratio = go_avg / rust_avg
                print(f"  {p.upper()}: Rust {rust_avg:.2f}μs vs Go {go_avg:.2f}μs (Go is {ratio:.2f}x slower)")

def analyze_scalability(grouped):
    """Analyze scalability across thread counts."""
    print("\n" + "="*80)
    print("SCALABILITY ANALYSIS")
    print("="*80)
    
    for lang in ['rust', 'go']:
        if lang not in grouped:
            continue
        
        print(f"\n{lang.upper()}:")
        
        # Group by distribution
        by_dist = defaultdict(list)
        for config_key, runs in grouped[lang].items():
            threads, dist = config_key
            avg_ops = mean([r['metrics']['ops_per_sec'] for r in runs])
            by_dist[dist].append((threads, avg_ops))
        
        for dist in sorted(by_dist.keys()):
            print(f"  Distribution: {dist}")
            data = sorted(by_dist[dist])
            
            if len(data) > 1:
                single_thread = data[0][1]
                max_threads = data[-1][0]
                max_ops = data[-1][1]
                scaling = max_ops / single_thread if single_thread > 0 else 0
                
                print(f"    1 thread:  {single_thread:,.0f} ops/sec")
                print(f"    {max_threads} threads: {max_ops:,.0f} ops/sec")
                print(f"    Scaling: {scaling:.2f}x")

def generate_insights(grouped):
    """Generate high-level insights."""
    print("\n" + "="*80)
    print("KEY INSIGHTS")
    print("="*80)
    
    # Overall speedup
    all_rust = []
    all_go = []
    for lang_data in grouped.values():
        for runs in lang_data.values():
            for r in runs:
                if r['config']['language'] == 'rust':
                    all_rust.append(r['metrics']['ops_per_sec'])
                else:
                    all_go.append(r['metrics']['ops_per_sec'])
    
    if all_rust and all_go:
        avg_rust = mean(all_rust)
        avg_go = mean(all_go)
        overall_speedup = calculate_speedup(avg_rust, avg_go)
        print(f"\n1. Overall Performance: Rust is {overall_speedup:.2f}x faster on average")
    
    # Best case
    best_rust = max(all_rust) if all_rust else 0
    best_go = max(all_go) if all_go else 0
    if best_rust > 0 and best_go > 0:
        best_speedup = calculate_speedup(best_rust, best_go)
        print(f"2. Peak Performance: Rust achieves {best_rust:,.0f} ops/sec vs Go's {best_go:,.0f} ops/sec ({best_speedup:.2f}x)")
    
    # Latency comparison
    rust_latencies = []
    go_latencies = []
    for lang_data in grouped.values():
        for runs in lang_data.values():
            for r in runs:
                p99 = r['metrics']['latency_us_p99']
                if r['config']['language'] == 'rust':
                    rust_latencies.append(p99)
                else:
                    go_latencies.append(p99)
    
    if rust_latencies and go_latencies:
        avg_rust_p99 = mean(rust_latencies)
        avg_go_p99 = mean(go_latencies)
        if avg_rust_p99 > 0 and avg_go_p99 > 0:
            latency_ratio = avg_go_p99 / avg_rust_p99
            print(f"3. Latency: Average P99 latency - Rust {avg_rust_p99:.2f}μs vs Go {avg_go_p99:.2f}μs")
            if latency_ratio > 1.1:
                print(f"   Go's P99 latency is {latency_ratio:.2f}x higher (worse)")
            elif latency_ratio < 0.9:
                print(f"   Rust's P99 latency is {1/latency_ratio:.2f}x higher (worse)")
            else:
                print(f"   Latencies are similar ({latency_ratio:.2f}x difference)")
    
    print("\n" + "="*80)

def main():
    results = load_results()
    
    if not results:
        print("No results found in results/*.json")
        return
    
    print(f"Analyzing {len(results)} benchmark results...")
    
    grouped = group_by_config(results)
    
    analyze_throughput(grouped)
    analyze_latency(grouped)
    analyze_scalability(grouped)
    generate_insights(grouped)
    
    print("\nAnalysis complete!")

if __name__ == '__main__':
    main()

