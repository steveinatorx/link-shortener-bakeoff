# Link Shortener Benchmark: Rust vs Go

A fair, reproducible performance comparison between Rust and Go for a core in-memory link shortener engine. This benchmark focuses on **core data structure operations only** - no HTTP server, no network I/O.

## Overview

This benchmark compares:
- **Throughput**: Operations per second
- **Latency**: p50, p95, p99 percentiles in microseconds
- **Scalability**: Performance across different thread counts

Both implementations use identical:
- Sharded hash map data structure (128 shards by default)
- FNV-1a 64-bit hash function for shard selection
- Pre-generated workload (same operations for both languages)
- Measurement methodology (warmup + measurement phases)

## Prerequisites

### Toolchain Management (asdf)

This project uses [asdf](https://asdf-vm.com/) for managing language versions:

```bash
# First, install asdf plugins (if not already installed)
asdf plugin add rust || true  # Ignore if already added
asdf plugin add golang || true
asdf plugin add python || true

# Then install versions specified in .tool-versions
asdf install
```

### Python Dependencies (pipenv)

**Note**: If Python 3.11.0 fails to build via asdf (common on macOS), you can:
- Use your system Python: `pipenv install --python $(which python3)`
- Or install Xcode command line tools: `xcode-select --install`
- Or use a different Python version in `.tool-versions`

```bash
# Install pipenv if not already installed
pip install pipenv

# Install Python dependencies
pipenv install
```

## Quick Start

### 1. Generate Workload

```bash
pipenv run python scripts/gen_workload.py \
    --n_initial 100000 \
    --n_ops 5000000 \
    --read_pct 95 \
    --dist uniform \
    --seed 12345
```

This creates:
- `data/initial.tsv`: Initial code→URL mappings
- `data/ops.txt`: Operation sequence (GET/SET)

### 2. Build Benchmarks

**Rust:**
```bash
cd bench-rust-core
cargo build --release
cd ..
```

**Go:**
```bash
cd bench-go-core
go build -o bench-go-core main.go
cd ..
```

### 3. Run Single Benchmark

**Rust:**
```bash
./bench-rust-core/target/release/bench-rust-core \
    --initial data/initial.tsv \
    --ops data/ops.txt \
    --threads 8 \
    --shards 128 \
    --warmup_s 2.0 \
    --duration_s 10.0 \
    --out results/rust_result.json
```

**Go:**
```bash
./bench-go-core/bench-go-core \
    -initial data/initial.tsv \
    -ops data/ops.txt \
    -threads 8 \
    -shards 128 \
    -warmup 2.0 \
    -duration 10.0 \
    -out results/go_result.json
```

### 4. Run Full Test Matrix

```bash
./scripts/run_all.sh
```

This will:
- Generate workloads for different sizes and distributions
- Run both benchmarks across multiple thread counts
- Generate plots in `plots/out/`

### 5. Generate Plots

```bash
pipenv run python plots/plot.py
```

Plots are saved to `plots/out/`:
- `ops_per_sec.png`: Throughput vs thread count
- `latency_p99.png`: P99 latency vs thread count

## Fairness Rules

To ensure a fair comparison:

1. **Same Data Structure**: Both use sharded hash maps with identical sharding logic
2. **Same Hash Function**: FNV-1a 64-bit implemented locally in both languages
3. **Same Workload**: Both read from the same pre-generated operation files
4. **Same Algorithm**: Identical operation logic and concurrency model
5. **No Language-Specific Optimizations**: Avoid unsafe tricks that can't be mirrored

See `spec/benchmark.md` for detailed benchmark rules.

## Project Structure

```
.
├── spec/
│   ├── benchmark.md          # Benchmark specification
│   └── results_schema.md     # Results JSON schema
├── data/                     # Generated workloads (gitignored)
├── results/                  # Benchmark results (gitignored)
├── plots/
│   ├── plot.py              # Plotting script
│   └── out/                  # Generated charts (gitignored)
├── bench-rust-core/          # Rust benchmark
│   ├── Cargo.toml
│   └── src/main.rs
├── bench-go-core/            # Go benchmark
│   ├── go.mod
│   └── main.go
├── scripts/
│   ├── gen_workload.py      # Workload generator
│   ├── run_all.sh           # Full test matrix runner
│   └── env.sh               # Toolchain version checker
├── .tool-versions            # asdf version pinning
├── Pipfile                   # Python dependencies
└── README.md
```

## Configuration

### Workload Parameters

- `--n_initial`: Number of initial entries (default: 100000)
- `--n_ops`: Number of operations (default: 5000000)
- `--read_pct`: Percentage of read operations (default: 95)
- `--dist`: Key distribution (`uniform` or `hot`, default: `uniform`)
- `--seed`: Random seed for reproducibility (default: 12345)

### Benchmark Parameters

- `--threads` / `-threads`: Number of worker threads (default: 1)
- `--shards` / `-shards`: Number of hash map shards (default: 128)
- `--warmup_s` / `-warmup`: Warmup duration in seconds (default: 2.0)
- `--duration_s` / `-duration`: Measurement duration in seconds (default: 10.0)

## Results Format

Results are written in two formats:

1. **JSON**: Full structured data (see `spec/results_schema.md`)
2. **CSV**: Appended to `results/results.csv` for easy analysis

## Reducing Measurement Noise

For more consistent results:

1. **Close unnecessary applications** to reduce CPU contention
2. **Plug in power** (for laptops) to avoid power throttling
3. **Run multiple times** and take median/average
4. **Warm up the machine** before benchmarking
5. **Use fixed CPU frequency** if possible (macOS: check with `sudo powermetrics`)

See `spec/benchmark.md` for more tips.

## Troubleshooting

### macOS-Specific

- **File descriptor limits**: Not needed (no HTTP server)
- **ulimits**: Default limits should be sufficient
- **Power management**: Consider disabling Turbo Boost for consistency (optional)

### Build Issues

- **Rust not found**: Run `asdf install` to install Rust version from `.tool-versions`
- **Go not found**: Run `asdf install` to install Go version from `.tool-versions`
- **Python dependencies**: Run `pipenv install` to install matplotlib

### Runtime Issues

- **Permission denied**: Ensure scripts are executable: `chmod +x scripts/*.sh`
- **File not found**: Generate workload first with `gen_workload.py`
- **Out of memory**: Reduce `--n_initial` or `--n_ops` for smaller datasets

## License

This is a benchmark project for performance comparison purposes.

