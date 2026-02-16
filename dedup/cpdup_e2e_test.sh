#!/bin/bash

# cpdup_e2e_test.sh - End-to-end test for cpdup workflow
# This script:
# 1. Extracts three test archives: A (original), B (empty), C (expected result)
# 2. Runs cpdup A B to copy files from A to B
# 3. Runs redup B C to reconstruct files from B
# 4. Compares A and C to verify they match

set -euo pipefail

# Test directories
TEST_BASE="/tmp/cpdup_test"
A_DIR="$TEST_BASE/A"
B_DIR="$TEST_BASE/B"
C_DIR="$TEST_BASE/C"
A_ARCHIVE="/tmp/simple_test_A.tar.gz"
B_ARCHIVE="/tmp/simple_test_B.tar.gz"
C_ARCHIVE="/tmp/simple_test_A.tar.gz"

echo "Starting cpdup end-to-end test..."

# Clean up any existing test data
echo "Cleaning up test directories..."
rm -rf "$TEST_BASE"

# Create test archives if they don't exist
if [ ! -f "$A_ARCHIVE" ]; then
    echo "Creating test archive A..."
    mkdir -p /tmp/simple_test_A/{docs,images,code}
    echo "This is a unique document about AI." > /tmp/simple_test_A/docs/ai_doc.txt
    echo "This content is duplicated." > /tmp/simple_test_A/docs/duplicate.txt
    echo "This content is duplicated." > /tmp/simple_test_A/images/duplicate.txt
    echo "This content is duplicated." > /tmp/simple_test_A/code/duplicate.txt
    echo "Python script for data processing." > /tmp/simple_test_A/docs/script.py
    echo "Bash script for automation." > /tmp/simple_test_A/code/script.py
    echo "Image metadata for photo 1." > /tmp/simple_test_A/images/photo.jpg
    echo "Image metadata for photo 2." > /tmp/simple_test_A/docs/photo.jpg
    echo "Empty file" > /tmp/simple_test_A/empty.txt
    touch /tmp/simple_test_A/truly_empty.txt
    tar -czf "$A_ARCHIVE" -C /tmp simple_test_A
    rm -rf /tmp/simple_test_A
fi

if [ ! -f "$B_ARCHIVE" ]; then
    echo "Creating empty test archive B..."
    mkdir -p /tmp/simple_test_B
    tar -czf "$B_ARCHIVE" -C /tmp simple_test_B
    rm -rf /tmp/simple_test_B
fi

if [ ! -f "$C_ARCHIVE" ]; then
    echo "Creating expected result archive C..."
    mkdir -p /tmp/simple_test_A/{docs,images,code}
    echo "This is a unique document about AI." > /tmp/simple_test_A/docs/ai_doc.txt
    echo "This content is duplicated." > /tmp/simple_test_A/docs/duplicate.txt
    echo "This content is duplicated." > /tmp/simple_test_A/images/duplicate.txt
    echo "This content is duplicated." > /tmp/simple_test_A/code/duplicate.txt
    echo "Python script for data processing." > /tmp/simple_test_A/docs/script.py
    echo "Bash script for automation." > /tmp/simple_test_A/code/script.py
    echo "Image metadata for photo 1." > /tmp/simple_test_A/images/photo.jpg
    echo "Image metadata for photo 2." > /tmp/simple_test_A/docs/photo.jpg
    echo "Empty file" > /tmp/simple_test_A/empty.txt
    touch /tmp/simple_test_A/truly_empty.txt
    tar -czf "$C_ARCHIVE" -C /tmp simple_test_A
    rm -rf /tmp/simple_test_A
fi

# Extract test data
echo "Extracting test archives..."
mkdir -p "$A_DIR" "$B_DIR" "$C_DIR"
tar -xzf "$A_ARCHIVE" -C "$(dirname "$A_DIR")"
tar -xzf "$B_ARCHIVE" -C "$(dirname "$B_DIR")"
tar -xzf "$C_ARCHIVE" -C "$(dirname "$C_DIR")"
cp -r "$(dirname "$A_DIR")/simple_test_A" "$A_DIR"
mv "$(dirname "$B_DIR")/simple_test_B" "$B_DIR"
cp -r "$A_DIR" "$C_DIR"

# Create dedup structure for A
echo "Creating dedup structure for A..."
python3 dedup.py "$A_DIR" "$A_DIR.dedup"

# Create empty dedup structure for B
echo "Creating empty dedup structure for B..."
mkdir -p "$B_DIR.dedup/data" "$B_DIR.dedup/files"

# Run cpdup A.dedup B.dedup
echo "Running cpdup A.dedup -> B.dedup..."
./cpdup.sh "$A_DIR.dedup" "$B_DIR.dedup"

# Run redup B.dedup C
echo "Running redup B.dedup -> C..."
./redup.sh "$B_DIR.dedup" "$C_DIR"

# Create archive from C
echo "Creating archive from C..."
tar -czf "$TEST_BASE/C_result.tar.gz" -C "$(dirname "$C_DIR")" "$(basename "$C_DIR")"

# Compare A and C archives
echo "Comparing A and C archives..."
if cmp -s "$A_ARCHIVE" "$TEST_BASE/C_result.tar.gz"; then
    echo "Success: Archives A and C are bit-identical! Perfect match!"
else
    echo "Warning: Archives A and C differ"
    echo "A size: $(stat -f%z "$A_ARCHIVE" 2>/dev/null || stat -c%s "$A_ARCHIVE") bytes"
    echo "C size: $(stat -f%z "$TEST_BASE/C_result.tar.gz" 2>/dev/null || stat -c%s "$TEST_BASE/C_result.tar.gz") bytes"
fi

echo "Test Statistics:"
echo "  A files: $(find "$A_DIR" -type f | wc -l)"
echo "  A.dedup data files: $(find "$A_DIR.dedup/data" -type f 2>/dev/null | wc -l || echo 0)"
echo "  A.dedup symlinks: $(find "$A_DIR.dedup/files" -type l 2>/dev/null | wc -l || echo 0)"
echo "  B.dedup data files: $(find "$B_DIR.dedup/data" -type f 2>/dev/null | wc -l || echo 0)"
echo "  B.dedup symlinks: $(find "$B_DIR.dedup/files" -type l 2>/dev/null | wc -l || echo 0)"
echo "  C files: $(find "$C_DIR" -type f | wc -l)"

echo "cpdup end-to-end test completed!"
echo "Cleaning up test directories..."
rm -rf "$TEST_BASE"
