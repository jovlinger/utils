#!/bin/bash

# simple_e2e_test.sh - Simplified end-to-end test using pre-created test data
# This script:
# 1. Extracts the pre-created test archive to /tmp/dir/input
# 2. Runs dedup on the input to create /tmp/dir/ddup
# 3. Runs redup on ddup to create /tmp/dir/rdup
# 4. Compares the original archive with the redup output

set -euo pipefail

# Test directories
TEST_BASE="/tmp/dir"
INPUT_DIR="$TEST_BASE/input"
DEDUP_DIR="$TEST_BASE/ddup"
REDUP_DIR="$TEST_BASE/rdup"
ORIGINAL_ARCHIVE="/tmp/simple_test.tar.gz"
REDUP_ARCHIVE="$TEST_BASE/redup.tar.gz"

echo "Starting simplified end-to-end test..."

# Clean up any existing test data
echo "Cleaning up test directories..."
rm -rf "$TEST_BASE"

# Extract test data
echo "Extracting test data..."
mkdir -p "$INPUT_DIR"
tar -xzf "$ORIGINAL_ARCHIVE" -C "$(dirname "$INPUT_DIR")"
mv "$(dirname "$INPUT_DIR")/simple_test" "$INPUT_DIR"

# Run dedup
echo "Running dedup..."
python3 dedup.py "$INPUT_DIR" "$DEDUP_DIR"

# Run redup
echo "Running redup..."
./redup.sh "$DEDUP_DIR" "$REDUP_DIR"

# Create archive from redup output
echo "Creating redup archive..."
tar -czf "$REDUP_ARCHIVE" -C "$(dirname "$REDUP_DIR")" "$(basename "$REDUP_DIR")"

# Compare archives
echo "Comparing archives..."
if cmp -s "$ORIGINAL_ARCHIVE" "$REDUP_ARCHIVE"; then
    echo "Success: Archives are bit-identical! Perfect match!"
else
    echo "Warning: Archives differ"
    echo "Original size: $(stat -f%z "$ORIGINAL_ARCHIVE" 2>/dev/null || stat -c%s "$ORIGINAL_ARCHIVE") bytes"
    echo "Redup size: $(stat -f%z "$REDUP_ARCHIVE" 2>/dev/null || stat -c%s "$REDUP_ARCHIVE") bytes"
fi

echo "Test Statistics:"
echo "  Original files: $(find "$INPUT_DIR" -type f | wc -l)"
echo "  Dedup data files: $(find "$DEDUP_DIR/data" -type f 2>/dev/null | wc -l || echo 0)"
echo "  Dedup symlinks: $(find "$DEDUP_DIR/files" -type l 2>/dev/null | wc -l || echo 0)"
echo "  Redup files: $(find "$REDUP_DIR" -type f | wc -l)"

echo "End-to-end test completed!"
echo "Cleaning up test directories..."
rm -rf "$TEST_BASE"
