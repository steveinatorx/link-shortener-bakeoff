#!/bin/bash
# Print toolchain versions and machine info for benchmark metadata

echo "=== Toolchain Versions ==="
echo "Rust:"
rustc --version 2>/dev/null || echo "  Not found"
cargo --version 2>/dev/null || echo "  Not found"

echo ""
echo "Go:"
go version 2>/dev/null || echo "  Not found"

echo ""
echo "Python:"
python3 --version 2>/dev/null || echo "  Not found"

echo ""
echo "=== Machine Info ==="
echo "OS: $(uname -s)"
echo "Arch: $(uname -m)"
echo "CPU Cores: $(sysctl -n hw.ncpu 2>/dev/null || nproc 2>/dev/null || echo 'unknown')"
echo "Hostname: $(hostname 2>/dev/null || echo 'unknown')"

echo ""
echo "=== Git Info ==="
git rev-parse --short=12 HEAD 2>/dev/null || echo "  Not a git repo or git not found"

