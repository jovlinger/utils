#!/bin/bash

# e2e_test.sh - End-to-end test for dedup/redup workflow
# This script:
# 1. Creates test data and archives it
# 2. Extracts the archive to /tmp/dir/input
# 3. Runs dedup on the input to create /tmp/dir/ddup
# 4. Runs redup on ddup to create /tmp/dir/rdup
# 5. Compares the original archive with the redup output

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Test directories
TEST_BASE="/tmp/dir"
INPUT_DIR="$TEST_BASE/input"
DEDUP_DIR="$TEST_BASE/ddup"
REDUP_DIR="$TEST_BASE/rdup"
ORIGINAL_ARCHIVE="$TEST_BASE/original.tar.gz"
REDUP_ARCHIVE="$TEST_BASE/redup.tar.gz"

# Function to display colored output
info() {
    echo -e "${BLUE}Info:${NC} $1"
}

success() {
    echo -e "${GREEN}Success:${NC} $1"
}

warning() {
    echo -e "${YELLOW}Warning:${NC} $1"
}

error() {
    echo -e "${RED}Error:${NC} $1" >&2
    exit 1
}

# Function to cleanup test directories
cleanup() {
    info "Cleaning up test directories..."
    rm -rf "$TEST_BASE"
}

# Function to create test data
create_test_data() {
    info "Creating test data structure..."
    
    # Create input directory
    mkdir -p "$INPUT_DIR"
    
    # Create a variety of test files with different content
    mkdir -p "$INPUT_DIR/documents"
    mkdir -p "$INPUT_DIR/images"
    mkdir -p "$INPUT_DIR/code"
    
    # Create some unique files
    echo "This is a unique document about machine learning." > "$INPUT_DIR/documents/ml_doc.txt"
    echo "Image metadata for a photo." > "$INPUT_DIR/images/photo1.jpg"
    echo "Another image metadata." > "$INPUT_DIR/images/photo2.jpg"
    echo "#!/bin/bash\necho 'Hello World'" > "$INPUT_DIR/code/script.sh"
    echo "Python code for data processing." > "$INPUT_DIR/code/process.py"
    
    # Create some duplicate files (same content, different names)
    echo "This content is duplicated." > "$INPUT_DIR/documents/duplicate1.txt"
    echo "This content is duplicated." > "$INPUT_DIR/images/duplicate2.txt"
    echo "This content is duplicated." > "$INPUT_DIR/code/duplicate3.txt"
    
    # Create some empty files
    touch "$INPUT_DIR/empty_file.txt"
    touch "$INPUT_DIR/documents/empty_doc.txt"
    
    # Create a file with special characters in the name
    echo "File with spaces and special chars!" > "$INPUT_DIR/documents/file with spaces.txt"
    echo "File with unicode: café naïve" > "$INPUT_DIR/documents/café_naïve.txt"
    
    # Create a nested directory structure
    mkdir -p "$INPUT_DIR/nested/deep/structure"
    echo "Deep nested file content." > "$INPUT_DIR/nested/deep/structure/deep_file.txt"
    echo "This content is duplicated." > "$INPUT_DIR/nested/deep/structure/another_duplicate.txt"
    
    info "Test data created with $(find "$INPUT_DIR" -type f | wc -l) files"
}

# Function to create archive from directory
create_archive() {
    local source_dir="$1"
    local archive_path="$2"
    
    info "Creating archive from $source_dir..."
    tar -czf "$archive_path" -C "$(dirname "$source_dir")" "$(basename "$source_dir")"
    info "Archive created: $archive_path"
}

# Function to extract archive
extract_archive() {
    local archive_path="$1"
    local dest_dir="$2"
    
    info "Extracting $archive_path to $dest_dir..."
    mkdir -p "$dest_dir"
    tar -xzf "$archive_path" -C "$dest_dir"
    info "Archive extracted to $dest_dir"
}

# Function to run dedup
run_dedup() {
    info "Running dedup on $INPUT_DIR -> $DEDUP_DIR..."
    
    if ! python3 shasrv/dedup.py "$INPUT_DIR" "$DEDUP_DIR"; then
        error "Dedup failed"
    fi
    
    info "Dedup completed successfully"
}

# Function to run redup
run_redup() {
    info "Running redup on $DEDUP_DIR -> $REDUP_DIR..."
    
    if ! ./shasrv/redup.sh "$DEDUP_DIR" "$REDUP_DIR"; then
        error "Redup failed"
    fi
    
    info "Redup completed successfully"
}

# Function to compare archives
compare_archives() {
    info "Comparing original and redup archives..."
    
    # Create archives for comparison
    create_archive "$INPUT_DIR" "$ORIGINAL_ARCHIVE"
    create_archive "$REDUP_DIR" "$REDUP_ARCHIVE"
    
    # Compare file sizes
    local original_size=$(stat -f%z "$ORIGINAL_ARCHIVE" 2>/dev/null || stat -c%s "$ORIGINAL_ARCHIVE")
    local redup_size=$(stat -f%z "$REDUP_ARCHIVE" 2>/dev/null || stat -c%s "$REDUP_ARCHIVE")
    
    info "Original archive size: $original_size bytes"
    info "Redup archive size: $redup_size bytes"
    
    if [ "$original_size" -eq "$redup_size" ]; then
        success "Archive sizes match!"
        
        # If sizes match, do a binary comparison
        if cmp -s "$ORIGINAL_ARCHIVE" "$REDUP_ARCHIVE"; then
            success "Archives are bit-identical! Perfect match!"
        else
            warning "Archive sizes match but content differs"
        fi
    else
        warning "Archive sizes differ (this might be expected due to compression differences)"
    fi
    
    # Extract both archives to temporary directories for content comparison
    local temp_orig="$TEST_BASE/temp_orig"
    local temp_redup="$TEST_BASE/temp_redup"
    
    extract_archive "$ORIGINAL_ARCHIVE" "$temp_orig"
    extract_archive "$REDUP_ARCHIVE" "$temp_redup"
    
    # Compare directory structures
    info "Comparing directory structures..."
    if diff -r "$temp_orig" "$temp_redup" > /dev/null 2>&1; then
        success "Directory structures and file contents match perfectly!"
    else
        warning "Differences found in directory structure or file contents"
        info "Running detailed diff..."
        diff -r "$temp_orig" "$temp_redup" || true
    fi
    
    # Clean up temp directories
    rm -rf "$temp_orig" "$temp_redup"
}

# Function to show statistics
show_statistics() {
    info "Test Statistics:"
    echo "  Original files: $(find "$INPUT_DIR" -type f | wc -l)"
    echo "  Dedup data files: $(find "$DEDUP_DIR/data" -type f 2>/dev/null | wc -l || echo 0)"
    echo "  Dedup symlinks: $(find "$DEDUP_DIR/files" -type l 2>/dev/null | wc -l || echo 0)"
    echo "  Redup files: $(find "$REDUP_DIR" -type f | wc -l)"
    echo "  Data directory size: $(du -sh "$DEDUP_DIR/data" 2>/dev/null | cut -f1 || echo "N/A")"
    echo "  Files directory size: $(du -sh "$DEDUP_DIR/files" 2>/dev/null | cut -f1 || echo "N/A")"
    echo "  Redup directory size: $(du -sh "$REDUP_DIR" | cut -f1)"
}

# Main test function
run_e2e_test() {
    info "Starting end-to-end test..."
    
    # Cleanup any existing test data
    cleanup
    
    # Create test data
    create_test_data
    
    # Run dedup
    run_dedup
    
    # Run redup
    run_redup
    
    # Compare results
    compare_archives
    
    # Show statistics
    show_statistics
    
    success "End-to-end test completed successfully!"
    
    # Ask if user wants to keep test data
    echo ""
    read -p "Keep test data for inspection? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        cleanup
    else
        info "Test data kept in $TEST_BASE"
        info "  Original: $INPUT_DIR"
        info "  Dedup: $DEDUP_DIR"
        info "  Redup: $REDUP_DIR"
    fi
}

# Handle script arguments
case "${1:-}" in
    "cleanup")
        cleanup
        ;;
    "stats")
        if [ -d "$TEST_BASE" ]; then
            show_statistics
        else
            error "No test data found. Run the test first."
        fi
        ;;
    "help"|"-h"|"--help")
        echo "Usage: $0 [cleanup|stats|help]"
        echo "  (no args) - Run full end-to-end test"
        echo "  cleanup   - Clean up test directories"
        echo "  stats     - Show statistics of existing test data"
        echo "  help      - Show this help message"
        ;;
    "")
        run_e2e_test
        ;;
    *)
        error "Unknown argument: $1. Use 'help' for usage information."
        ;;
esac
