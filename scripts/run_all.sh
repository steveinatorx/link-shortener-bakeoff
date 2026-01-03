#!/bin/bash
# Run a matrix of benchmark tests

set -e

# Configuration
N_VALUES=(100000 1000000)
THREADS_VALUES=(1 2 4 8 12)
DIST_VALUES=(uniform hot)
READ_PCT=95
SEED=12345
WARMUP_S=2.0
DURATION_S=10.0
SHARDS=128

# Directories
DATA_DIR="data"
RESULTS_DIR="results"
PLOTS_DIR="plots/out"

# Create directories
mkdir -p "$DATA_DIR"
mkdir -p "$RESULTS_DIR"
mkdir -p "$PLOTS_DIR"

echo "=== Link Shortener Benchmark Suite ==="
echo ""

# Check if Rust and Go benchmarks are built
echo "Building benchmarks..."
cd bench-rust-core
if [ ! -f "target/release/bench-rust-core" ]; then
    echo "Building Rust benchmark..."
    cargo build --release
fi
cd ..

cd bench-go-core
if [ ! -f "bench-go-core" ]; then
    echo "Building Go benchmark..."
    go build -o bench-go-core main.go
fi
cd ..

echo ""

# Generate workloads if needed
for N in "${N_VALUES[@]}"; do
    for DIST in "${DIST_VALUES[@]}"; do
        INITIAL_FILE="$DATA_DIR/initial_n${N}_${DIST}.tsv"
        OPS_FILE="$DATA_DIR/ops_n${N}_${DIST}.txt"
        
        if [ ! -f "$INITIAL_FILE" ] || [ ! -f "$OPS_FILE" ]; then
            echo "Generating workload: N=$N, dist=$DIST..."
            # Use a seed that incorporates N and DIST for uniqueness
            WORKLOAD_SEED=$((SEED + N + $(echo "$DIST" | od -An -N1 -tu1 | tr -d ' ')))
            pipenv run python scripts/gen_workload.py \
                --n_initial "$N" \
                --n_ops 5000000 \
                --read_pct "$READ_PCT" \
                --dist "$DIST" \
                --seed "$WORKLOAD_SEED" \
                --out_dir "$DATA_DIR"
            
            # Rename to include N and dist
            mv "$DATA_DIR/initial.tsv" "$INITIAL_FILE"
            mv "$DATA_DIR/ops.txt" "$OPS_FILE"
        fi
    done
done

echo ""

# Run benchmarks
TIMESTAMP=$(date +%Y%m%d_%H%M%S)

for N in "${N_VALUES[@]}"; do
    for DIST in "${DIST_VALUES[@]}"; do
        INITIAL_FILE="$DATA_DIR/initial_n${N}_${DIST}.tsv"
        OPS_FILE="$DATA_DIR/ops_n${N}_${DIST}.txt"
        
        for THREADS in "${THREADS_VALUES[@]}"; do
            echo "Running: N=$N, dist=$DIST, threads=$THREADS"
            
            # Run Rust benchmark
            RUST_OUT="$RESULTS_DIR/${TIMESTAMP}_rust_n${N}_t${THREADS}_${DIST}.json"
            ./bench-rust-core/target/release/bench-rust-core \
                --initial "$INITIAL_FILE" \
                --ops "$OPS_FILE" \
                --threads "$THREADS" \
                --shards "$SHARDS" \
                --warmup_s "$WARMUP_S" \
                --duration_s "$DURATION_S" \
                --out "$RUST_OUT" || echo "Warning: Rust benchmark failed"
            
            # Run Go benchmark
            GO_OUT="$RESULTS_DIR/${TIMESTAMP}_go_n${N}_t${THREADS}_${DIST}.json"
            cd bench-go-core
            ./bench-go-core \
                -initial "../$INITIAL_FILE" \
                -ops "../$OPS_FILE" \
                -threads "$THREADS" \
                -shards "$SHARDS" \
                -warmup "$WARMUP_S" \
                -duration "$DURATION_S" \
                -out "../$GO_OUT" || echo "Warning: Go benchmark failed"
            cd ..
        done
    done
done

echo ""
echo "=== Generating plots ==="
pipenv run python plots/plot.py

echo ""
echo "=== Done ==="
echo "Results: $RESULTS_DIR"
echo "Plots: $PLOTS_DIR"

