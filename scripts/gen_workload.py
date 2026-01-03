#!/usr/bin/env python3
"""
Generate workload files for the link shortener benchmark.

Usage:
    python3 gen_workload.py --n_initial 100000 --n_ops 5000000 --read_pct 95 --dist uniform --seed 12345
"""

import argparse
import random
import string
import os
import sys

# Base62 alphabet
BASE62 = string.ascii_letters + string.digits

def base62_encode(n, length=8):
    """Encode a number to base62 string of fixed length."""
    if n == 0:
        return '0' * length
    result = []
    while n > 0:
        result.append(BASE62[n % 62])
        n //= 62
    # Pad to desired length
    while len(result) < length:
        result.append('0')
    return ''.join(reversed(result))[:length]

def generate_url(min_len=30, max_len=120):
    """Generate a random ASCII URL string."""
    length = random.randint(min_len, max_len)
    # Use printable ASCII (32-126), excluding control chars
    chars = string.ascii_letters + string.digits + string.punctuation
    return ''.join(random.choice(chars) for _ in range(length))

def generate_initial_dataset(n, seed):
    """Generate initial dataset of N code->url mappings."""
    random.seed(seed)
    entries = []
    seen_codes = set()
    
    code_counter = 0
    while len(entries) < n:
        # Use counter to ensure uniqueness
        code = base62_encode(code_counter)
        if code not in seen_codes:
            seen_codes.add(code)
            url = generate_url()
            entries.append((code, url))
        code_counter += 1
    
    return entries

def generate_ops_uniform(n_ops, initial_codes, read_pct, seed):
    """Generate operations with uniform key distribution."""
    random.seed(seed)
    ops = []
    
    n_reads = int(n_ops * read_pct / 100)
    n_writes = n_ops - n_reads
    
    # Generate reads: uniformly random from initial codes
    for _ in range(n_reads):
        code = random.choice(initial_codes)
        ops.append(('G', code, None))
    
    # Generate writes: new unique codes
    max_code = len(initial_codes)
    for i in range(n_writes):
        code = base62_encode(max_code + i)
        url = generate_url()
        ops.append(('S', code, url))
    
    # Shuffle to mix reads and writes
    random.shuffle(ops)
    return ops

def generate_ops_hot(n_ops, initial_codes, read_pct, seed):
    """Generate operations with hot (zipf-like) key distribution."""
    random.seed(seed)
    ops = []
    
    n_reads = int(n_ops * read_pct / 100)
    n_writes = n_ops - n_reads
    
    # Create hot set: top 20% of codes
    hot_size = max(1, len(initial_codes) // 5)
    hot_codes = initial_codes[:hot_size]
    cold_codes = initial_codes[hot_size:]
    
    # Generate reads: 80% from hot set, 20% from cold set
    hot_reads = int(n_reads * 0.8)
    cold_reads = n_reads - hot_reads
    
    for _ in range(hot_reads):
        code = random.choice(hot_codes)
        ops.append(('G', code, None))
    
    for _ in range(cold_reads):
        code = random.choice(cold_codes) if cold_codes else random.choice(initial_codes)
        ops.append(('G', code, None))
    
    # Generate writes: new unique codes
    max_code = len(initial_codes)
    for i in range(n_writes):
        code = base62_encode(max_code + i)
        url = generate_url()
        ops.append(('S', code, url))
    
    # Shuffle to mix reads and writes
    random.shuffle(ops)
    return ops

def main():
    parser = argparse.ArgumentParser(description='Generate workload files for link shortener benchmark')
    parser.add_argument('--n_initial', type=int, default=100000, help='Number of initial entries')
    parser.add_argument('--n_ops', type=int, default=5000000, help='Number of operations')
    parser.add_argument('--read_pct', type=int, default=95, help='Percentage of read operations (0-100)')
    parser.add_argument('--dist', choices=['uniform', 'hot'], default='uniform', help='Key distribution')
    parser.add_argument('--seed', type=int, default=12345, help='Random seed')
    parser.add_argument('--out_dir', type=str, default='data', help='Output directory')
    
    args = parser.parse_args()
    
    # Create output directory
    os.makedirs(args.out_dir, exist_ok=True)
    
    # Generate initial dataset
    print(f"Generating {args.n_initial} initial entries...")
    initial_entries = generate_initial_dataset(args.n_initial, args.seed)
    initial_codes = [code for code, _ in initial_entries]
    
    # Write initial.tsv
    initial_path = os.path.join(args.out_dir, 'initial.tsv')
    with open(initial_path, 'w') as f:
        for code, url in initial_entries:
            f.write(f"{code}\t{url}\n")
    print(f"Wrote {initial_path}")
    
    # Generate operations
    print(f"Generating {args.n_ops} operations ({args.read_pct}% reads, {args.dist} distribution)...")
    if args.dist == 'uniform':
        ops = generate_ops_uniform(args.n_ops, initial_codes, args.read_pct, args.seed + 1)
    else:
        ops = generate_ops_hot(args.n_ops, initial_codes, args.read_pct, args.seed + 1)
    
    # Write ops.txt
    ops_path = os.path.join(args.out_dir, 'ops.txt')
    with open(ops_path, 'w') as f:
        for op_type, code, url in ops:
            if op_type == 'G':
                f.write(f"G {code}\n")
            else:
                f.write(f"S {code} {url}\n")
    print(f"Wrote {ops_path}")
    
    print(f"Done! Seed: {args.seed}")

if __name__ == '__main__':
    main()

