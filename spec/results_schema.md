# Results Schema

Both Rust and Go benchmarks must output JSON files conforming to this schema.

## JSON Structure

```json
{
  "meta": {
    "timestamp_utc": "2024-01-15T10:30:00Z",
    "os": "darwin",
    "arch": "arm64",
    "cpu_cores": 8,
    "hostname": "hostname.example.com"
  },
  "config": {
    "language": "rust",
    "language_version": "1.75.0",
    "git_commit": "abc123def456...",
    "n_initial": 100000,
    "ops_file": "data/ops.txt",
    "read_pct": 95,
    "dist": "uniform",
    "threads": 8,
    "shards": 128,
    "seed": 12345,
    "warmup_s": 2.0,
    "duration_s": 10.0
  },
  "metrics": {
    "ops_total": 5000000,
    "ops_per_sec": 500000.0,
    "latency_us_p50": 0.5,
    "latency_us_p95": 2.1,
    "latency_us_p99": 5.3,
    "rss_bytes": 52428800
  }
}
```

## Field Descriptions

### meta

- `timestamp_utc`: ISO 8601 UTC timestamp when benchmark started
- `os`: Operating system (e.g., "darwin", "linux", "windows")
- `arch`: CPU architecture (e.g., "arm64", "x86_64", "amd64")
- `cpu_cores`: Number of CPU cores (logical cores)
- `hostname`: Hostname of the machine (optional, may be omitted)

### config

- `language`: "rust" or "go"
- `language_version`: Toolchain version (e.g., "1.75.0" for Rust, "go1.22.0" for Go)
- `git_commit`: Git commit hash (short form, 12 chars) if available, empty string otherwise
- `n_initial`: Number of initial entries loaded
- `ops_file`: Path to the operations file used
- `read_pct`: Percentage of operations that are reads (0-100)
- `dist`: Distribution mode ("uniform" or "hot")
- `threads`: Number of worker threads/goroutines
- `shards`: Number of shards in the hash map
- `seed`: Random seed used to generate the workload
- `warmup_s`: Warmup duration in seconds
- `duration_s`: Measurement duration in seconds

### metrics

- `ops_total`: Total number of operations executed during measurement phase
- `ops_per_sec`: Operations per second (ops_total / duration_s)
- `latency_us_p50`: 50th percentile latency in microseconds
- `latency_us_p95`: 95th percentile latency in microseconds
- `latency_us_p99`: 99th percentile latency in microseconds
- `rss_bytes`: Resident Set Size in bytes (optional, may be null if unavailable)

## CSV Format

In addition to JSON, each run appends a line to `results/results.csv` with the following columns (in order):

```
timestamp_utc,language,language_version,git_commit,os,arch,cpu_cores,n_initial,read_pct,dist,threads,shards,seed,warmup_s,duration_s,ops_total,ops_per_sec,latency_us_p50,latency_us_p95,latency_us_p99,rss_bytes
```

Values are comma-separated. Missing optional fields (like `rss_bytes`) should be empty (two consecutive commas).

## Notes

- All numeric fields should be numbers (not strings) in JSON
- Timestamps should be in UTC
- Latency values are in microseconds (float)
- If a metric cannot be collected, use `null` in JSON or empty string in CSV

