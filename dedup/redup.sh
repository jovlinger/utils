#!/bin/bash

# redup.sh - Reconstruct files directory with actual contents instead of symlinks
# Usage: redup.sh <source_dir> [destination_dir]
#   source_dir: Directory containing data/ and files/ subdirectories
#   destination_dir: Where to create the reconstructed files (default: ./dup)

set -euo pipefail

# Default destination directory
DEST_DIR="./dup"

# Function to display usage
usage() {
    echo "Usage: $0 <source_dir> [destination_dir]"
    echo "  source_dir: Directory containing data/ and files/ subdirectories"
    echo "  destination_dir: Where to create the reconstructed files (default: ./dup)"
    echo ""
    echo "This utility reconstructs the files directory with actual file contents"
    echo "instead of symlinks, copying from the data/ directory structure."
    exit 1
}

# Function to display error messages
error() {
    echo "Error: $1" >&2
    exit 1
}

# Function to display info messages
info() {
    echo "Info: $1"
}

# Check arguments
if [ $# -lt 1 ] || [ $# -gt 2 ]; then
    usage
fi

SOURCE_DIR="$1"
if [ $# -eq 2 ]; then
    DEST_DIR="$2"
fi

# Validate source directory exists
if [ ! -d "$SOURCE_DIR" ]; then
    error "Source directory '$SOURCE_DIR' does not exist"
fi

# Check for required subdirectories
if [ ! -d "$SOURCE_DIR/data" ]; then
    error "Source directory '$SOURCE_DIR' does not contain a 'data' subdirectory"
fi

if [ ! -d "$SOURCE_DIR/files" ]; then
    error "Source directory '$SOURCE_DIR' does not contain a 'files' subdirectory"
fi

# Create destination directory if it doesn't exist
if [ ! -d "$DEST_DIR" ]; then
    info "Creating destination directory: $DEST_DIR"
    mkdir -p "$DEST_DIR"
fi

# Function to process a single file/symlink
process_file() {
    local file_path="$1"
    local relative_path="$2"
    local dest_file="$DEST_DIR/$relative_path"
    local dest_dir
    dest_dir=$(dirname "$dest_file")
    
    # Create destination directory if needed
    if [ ! -d "$dest_dir" ]; then
        mkdir -p "$dest_dir"
    fi
    
    if [ -L "$file_path" ]; then
        # It's a symlink, copy the target
        local target_path
        target_path=$(readlink "$file_path")
        
        # Handle relative symlinks by resolving them relative to the symlink's directory
        if [[ "$target_path" != /* ]]; then
            local symlink_dir
            symlink_dir=$(dirname "$file_path")
            target_path="$symlink_dir/$target_path"
        fi
        
        # Resolve any remaining relative path components (.., ., etc.)
        target_path=$(realpath "$target_path" 2>/dev/null || echo "$target_path")
        
        if [ -f "$target_path" ]; then
            info "Copying: $relative_path -> $target_path"
            cp "$target_path" "$dest_file"
        else
            error "Symlink target '$target_path' does not exist for '$relative_path'"
        fi
    elif [ -f "$file_path" ]; then
        # It's a regular file, copy it
        info "Copying: $relative_path"
        cp "$file_path" "$dest_file"
    else
        error "Unknown file type for '$relative_path'"
    fi
}

# Main processing
info "Reconstructing files from '$SOURCE_DIR' to '$DEST_DIR'"

# Count total files for progress
total_files=$(find "$SOURCE_DIR/files" -type f -o -type l | wc -l)
current_file=0

# Process all files and symlinks in the files directory
while IFS= read -r -d '' file_path; do
    current_file=$((current_file + 1))
    
    # Calculate relative path from files directory
    relative_path="${file_path#$SOURCE_DIR/files/}"
    
    # Skip if it's the files directory itself
    if [ "$relative_path" = "" ]; then
        continue
    fi
    
    echo "[$current_file/$total_files] Processing: $relative_path"
    process_file "$file_path" "$relative_path"
    
done < <(find "$SOURCE_DIR/files" -type f -o -type l -print0)

info "Reconstruction complete! $total_files files processed."
info "Output directory: $DEST_DIR"