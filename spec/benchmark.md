# Benchmark Specification

## Overview

This benchmark compares Rust and Go performance for a core in-memory link shortener engine. The benchmark focuses on **core data structure operations only** - no HTTP server, no network I/O, no disk I/O during measurement.

## What is Measured

- **Operations per second**: Throughput of GET (lookup) and SET (insert) operations
- **Latency percentiles**: p50, p95, p99 in microseconds
- **Memory usage**: RSS (Resident Set Size) in bytes (best-effort)

## What is NOT Measured

- HTTP request parsing/response generation
- Network stack overhead
- Disk I/O
- Garbage collection pauses (though GC may affect latency in Go)
- Compilation time
- Startup/shutdown time

## Workload Specification

### Dataset

- **Initial entries**: N entries mapping code → URL
  - `code`: base62 string, length 8 (e.g., "aB3xY9mK")
  - `url`: ASCII string, length 30-120 bytes (random printable ASCII)
- **Operation sequence**: Pre-generated M operations
  - Format: `G <code>` for GET, `S <code> <url>` for SET
  - Operations are generated deterministically from a seed
  - Same seed produces identical workload for both languages

### Operation Mix

- Default: 95% GET (lookup), 5% SET (insert)
- Configurable via `--read_pct` flag (percentage of reads, 0-100)

### Key Distribution Modes

1. **uniform**: Keys chosen uniformly at random from existing keys (for GETs). Inserts create new unique keys.
2. **hot**: Zipf-like distribution where ~80% of GETs hit ~20% of keys. Simple deterministic implementation.

### Concurrency Model

- T worker threads/goroutines (configurable)
- Each worker executes its assigned slice of pre-generated operations
- Workers iterate through their slice repeatedly to fill warmup + measurement duration

### Timing Phases

1. **Warmup phase** (default 2s, configurable)
   - Execute operations but do NOT record metrics
   - Allows JIT warmup, cache warming, etc.

2. **Measurement phase** (default 10s, configurable)
   - Execute operations and record all metrics
   - Record latency for each operation
   - Count total operations

## Fairness Rules

### Data Structure

- **Sharded hash maps**: Both languages use the same sharding strategy
  - Default: 128 shards (configurable)
  - Rust: `Vec<RwLock<HashMap<String, String>>>`
  - Go: `[]struct{ mu sync.RWMutex; m map[string]string }`

### Shard Selection

- Use **FNV-1a 64-bit hash** for shard selection
- Implement locally in both languages (no external dependencies)
- Formula: `shard_index = fnv1a64(code) % num_shards`

### Key/Value Storage

- Use natural string types (Rust `String`, Go `string`)
- No compression or encoding differences
- No unsafe tricks that can't be mirrored in both languages

### Operation Trace

- Both benchmarks read the **same pre-generated files**
- Format: newline-delimited text
  - GET: `G <code>\n`
  - SET: `S <code> <url>\n`
- Generator uses deterministic RNG (same seed = same output)

## Reducing Measurement Noise

1. **Close unnecessary applications** to reduce CPU contention
2. **Plug in power** (for laptops) to avoid power throttling
3. **Run multiple times** and take median/average
4. **Use fixed CPU frequency** if possible (macOS: `sudo powermetrics` to check)
5. **Disable Turbo Boost** if available (not required, but helps consistency)
6. **Warm up the machine** before benchmarking (run a few warmup iterations)

## Running the Benchmark

See `README.md` for exact commands. The benchmark supports:

- Configurable thread count
- Configurable shard count
- Configurable warmup and measurement duration
- Configurable operation mix and distribution
- Output to JSON and CSV

## Reproducibility

- All workloads are generated from seeds (recorded in results)
- Same seed + same config = same workload
- Results include git commit hash (if available) for code version tracking
- Results include toolchain versions for reproducibility

