#!/usr/bin/env python3
"""
Plot benchmark results from results/*.json files.

Usage:
    pipenv run python plots/plot.py
"""

import json
import os
import glob
import matplotlib.pyplot as plt
from collections import defaultdict
from matplotlib.ticker import FuncFormatter

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

def group_by_language(results):
    """Group results by language."""
    by_lang = defaultdict(list)
    for r in results:
        lang = r['config']['language']
        by_lang[lang].append(r)
    return by_lang

def format_millions(x, pos):
    """Format numbers as millions (e.g., 25M instead of 25000000)."""
    if x >= 1e6:
        return f'{x/1e6:.0f}M'
    elif x >= 1e3:
        return f'{x/1e3:.0f}K'
    else:
        return f'{x:.0f}'

def plot_ops_per_sec(results, output_dir="plots/out"):
    """Plot ops_per_sec vs threads."""
    by_lang = group_by_language(results)
    
    plt.figure(figsize=(10, 6))
    
    for lang, lang_results in sorted(by_lang.items()):
        # Group by thread count
        threads_data = defaultdict(list)
        for r in lang_results:
            threads = r['config']['threads']
            ops_per_sec = r['metrics']['ops_per_sec']
            threads_data[threads].append(ops_per_sec)
        
        # Compute average for each thread count
        threads_sorted = sorted(threads_data.keys())
        ops_avg = [sum(threads_data[t]) / len(threads_data[t]) for t in threads_sorted]
        
        plt.plot(threads_sorted, ops_avg, marker='o', label=lang.upper(), linewidth=2)
    
    plt.xlabel('Number of Threads', fontsize=12)
    plt.ylabel('Operations per Second', fontsize=12)
    plt.title('Throughput vs Thread Count', fontsize=14, fontweight='bold')
    plt.legend(fontsize=11)
    plt.grid(True, alpha=0.3)
    plt.gca().yaxis.set_major_formatter(FuncFormatter(format_millions))
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, "ops_per_sec.png")
    plt.savefig(output_path, dpi=150)
    print(f"Saved: {output_path}")
    plt.close()

def plot_latency_p99(results, output_dir="plots/out"):
    """Plot latency_p99 vs threads."""
    by_lang = group_by_language(results)
    
    plt.figure(figsize=(10, 6))
    
    for lang, lang_results in sorted(by_lang.items()):
        # Group by thread count
        threads_data = defaultdict(list)
        for r in lang_results:
            threads = r['config']['threads']
            p99 = r['metrics']['latency_us_p99']
            threads_data[threads].append(p99)
        
        # Compute average for each thread count
        threads_sorted = sorted(threads_data.keys())
        p99_avg = [sum(threads_data[t]) / len(threads_data[t]) for t in threads_sorted]
        
        plt.plot(threads_sorted, p99_avg, marker='s', label=lang.upper(), linewidth=2)
    
    plt.xlabel('Number of Threads', fontsize=12)
    plt.ylabel('P99 Latency (microseconds)', fontsize=12)
    plt.title('P99 Latency vs Thread Count', fontsize=14, fontweight='bold')
    plt.legend(fontsize=11)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    
    output_path = os.path.join(output_dir, "latency_p99.png")
    plt.savefig(output_path, dpi=150)
    print(f"Saved: {output_path}")
    plt.close()

def plot_read_vs_write(results, output_dir="plots/out"):
    """Plot read vs write throughput comparison."""
    by_lang = group_by_language(results)
    
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 6))
    
    for lang, lang_results in sorted(by_lang.items()):
        # Group by thread count
        threads_data = defaultdict(lambda: {'reads': [], 'writes': []})
        for r in lang_results:
            threads = r['config']['threads']
            reads = r['metrics'].get('reads_per_sec', 0)
            writes = r['metrics'].get('writes_per_sec', 0)
            threads_data[threads]['reads'].append(reads)
            threads_data[threads]['writes'].append(writes)
        
        threads_sorted = sorted(threads_data.keys())
        reads_avg = [sum(threads_data[t]['reads']) / len(threads_data[t]['reads']) 
                     for t in threads_sorted]
        writes_avg = [sum(threads_data[t]['writes']) / len(threads_data[t]['writes']) 
                      for t in threads_sorted]
        
        ax1.plot(threads_sorted, reads_avg, marker='o', label=f'{lang.upper()} Reads', linewidth=2)
        ax2.plot(threads_sorted, writes_avg, marker='s', label=f'{lang.upper()} Writes', linewidth=2)
    
    ax1.set_xlabel('Number of Threads', fontsize=12)
    ax1.set_ylabel('Read Ops/sec', fontsize=12)
    ax1.set_title('Read Throughput vs Thread Count', fontsize=13, fontweight='bold')
    ax1.legend(fontsize=10)
    ax1.grid(True, alpha=0.3)
    ax1.yaxis.set_major_formatter(FuncFormatter(format_millions))
    
    ax2.set_xlabel('Number of Threads', fontsize=12)
    ax2.set_ylabel('Write Ops/sec', fontsize=12)
    ax2.set_title('Write Throughput vs Thread Count', fontsize=13, fontweight='bold')
    ax2.legend(fontsize=10)
    ax2.grid(True, alpha=0.3)
    ax2.yaxis.set_major_formatter(FuncFormatter(format_millions))
    
    plt.tight_layout()
    output_path = os.path.join(output_dir, "read_vs_write.png")
    plt.savefig(output_path, dpi=150)
    print(f"Saved: {output_path}")
    plt.close()

def plot_read_write_latency(results, output_dir="plots/out"):
    """Plot read vs write latency comparison."""
    by_lang = group_by_language(results)
    
    fig, axes = plt.subplots(1, 3, figsize=(18, 6))
    percentiles = ['p50', 'p95', 'p99']
    percentile_keys = ['reads_latency_us_p50', 'reads_latency_us_p95', 'reads_latency_us_p99',
                       'writes_latency_us_p50', 'writes_latency_us_p95', 'writes_latency_us_p99']
    
    for idx, p in enumerate(percentiles):
        ax = axes[idx]
        read_key = f'reads_latency_us_{p}'
        write_key = f'writes_latency_us_{p}'
        
        for lang, lang_results in sorted(by_lang.items()):
            threads_data = defaultdict(lambda: {'reads': [], 'writes': []})
            for r in lang_results:
                threads = r['config']['threads']
                reads = r['metrics'].get(read_key, 0)
                writes = r['metrics'].get(write_key, 0)
                threads_data[threads]['reads'].append(reads)
                threads_data[threads]['writes'].append(writes)
            
            threads_sorted = sorted(threads_data.keys())
            reads_avg = [sum(threads_data[t]['reads']) / len(threads_data[t]['reads']) 
                         for t in threads_sorted]
            writes_avg = [sum(threads_data[t]['writes']) / len(threads_data[t]['writes']) 
                          for t in threads_sorted]
            
            ax.plot(threads_sorted, reads_avg, marker='o', linestyle='--', 
                   label=f'{lang.upper()} Reads', linewidth=2)
            ax.plot(threads_sorted, writes_avg, marker='s', linestyle='-', 
                   label=f'{lang.upper()} Writes', linewidth=2)
        
        ax.set_xlabel('Number of Threads', fontsize=11)
        ax.set_ylabel('Latency (μs)', fontsize=11)
        ax.set_title(f'{p.upper()} Latency: Reads vs Writes', fontsize=12, fontweight='bold')
        ax.legend(fontsize=9)
        ax.grid(True, alpha=0.3)
    
    plt.tight_layout()
    output_path = os.path.join(output_dir, "read_write_latency.png")
    plt.savefig(output_path, dpi=150)
    print(f"Saved: {output_path}")
    plt.close()

def print_summary(results):
    """Print a summary table of results."""
    print("\n" + "="*80)
    print("BENCHMARK SUMMARY")
    print("="*80)
    
    by_lang = group_by_language(results)
    
    for lang, lang_results in sorted(by_lang.items()):
        print(f"\n{lang.upper()}:")
        print(f"  {'Threads':<8} {'Ops/sec':<12} {'P50 (μs)':<12} {'P95 (μs)':<12} {'P99 (μs)':<12}")
        print("  " + "-"*60)
        
        # Group by threads
        threads_data = defaultdict(list)
        for r in lang_results:
            threads = r['config']['threads']
            threads_data[threads].append(r)
        
        for threads in sorted(threads_data.keys()):
            runs = threads_data[threads]
            ops_avg = sum(r['metrics']['ops_per_sec'] for r in runs) / len(runs)
            p50_avg = sum(r['metrics']['latency_us_p50'] for r in runs) / len(runs)
            p95_avg = sum(r['metrics']['latency_us_p95'] for r in runs) / len(runs)
            p99_avg = sum(r['metrics']['latency_us_p99'] for r in runs) / len(runs)
            
            reads_avg = sum(r['metrics'].get('reads_per_sec', 0) for r in runs) / len(runs)
            writes_avg = sum(r['metrics'].get('writes_per_sec', 0) for r in runs) / len(runs)
            
            print(f"  {threads:<8} {ops_avg:<12.0f} {p50_avg:<12.2f} {p95_avg:<12.2f} {p99_avg:<12.2f}")
            if reads_avg > 0 or writes_avg > 0:
                print(f"           Reads: {reads_avg:<10.0f} Writes: {writes_avg:<10.0f}")
    
    print("\n" + "="*80)

def main():
    results = load_results()
    
    if not results:
        print("No results found in results/*.json")
        return
    
    print(f"Loaded {len(results)} result files")
    
    os.makedirs("plots/out", exist_ok=True)
    
    plot_ops_per_sec(results)
    plot_latency_p99(results)
    plot_read_vs_write(results)
    plot_read_write_latency(results)
    print_summary(results)

if __name__ == '__main__':
    main()

