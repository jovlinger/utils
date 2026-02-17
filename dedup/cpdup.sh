#!/bin/bash

# cpdup.sh - Copy files between dedup-style filesystems
# Usage: cpdup.sh <src_dedup_dir> <dst_dedup_dir>
#   src_dedup_dir: Source dedup directory (with data/ and files/ subdirectories)
#   dst_dedup_dir: Destination dedup directory (will be created if needed)

set -euo pipefail

# Function to display usage
usage() {
    echo "Usage: $0 <src_dedup_dir> <dst_dedup_dir>"
    echo "  src_dedup_dir: Source dedup directory (with data/ and files/ subdirectories)"
    echo "  dst_dedup_dir: Destination dedup directory (will be created if needed)"
    echo ""
    echo "This utility copies all files from src to dst, preserving the dedup structure."
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
if [ $# -ne 2 ]; then
    usage
fi

SRC_DIR="$1"
DST_DIR="$2"

# Validate source directory exists
if [ ! -d "$SRC_DIR" ]; then
    error "Source directory '$SRC_DIR' does not exist"
fi

# Check for required subdirectories in source
if [ ! -d "$SRC_DIR/data" ]; then
    error "Source directory '$SRC_DIR' does not contain a 'data' subdirectory"
fi

if [ ! -d "$SRC_DIR/files" ]; then
    error "Source directory '$SRC_DIR' does not contain a 'files' subdirectory"
fi

# Create destination directory structure if it doesn't exist
if [ ! -d "$DST_DIR" ]; then
    info "Creating destination directory: $DST_DIR"
    mkdir -p "$DST_DIR"
fi

mkdir -p "$DST_DIR/data"
mkdir -p "$DST_DIR/files"

# Function to copy a single file/symlink
copy_file() {
    local file_path="$1"
    local relative_path="$2"
    local dst_file="$DST_DIR/files/$relative_path"
    local dst_dir
    dst_dir=$(dirname "$dst_file")
    
    # Create destination directory if needed
    if [ ! -d "$dst_dir" ]; then
        mkdir -p "$dst_dir"
    fi
    
    if [ -L "$file_path" ]; then
        # It's a symlink, copy it
        local target_path
        target_path=$(readlink "$file_path")
        
        # Handle relative symlinks by resolving them relative to the symlink's directory
        if [[ "$target_path" != /* ]]; then
            local symlink_dir
            symlink_dir=$(dirname "$file_path")
            target_path="$symlink_dir/$target_path"
        fi
        
        # Resolve any remaining relative path components
        target_path=$(realpath "$target_path" 2>/dev/null || echo "$target_path")
        
        if [ -f "$target_path" ]; then
            # Copy the target file to data directory if not already there
            local target_hash
            target_hash=$(basename "$target_path")
            local target_subdir
            target_subdir=$(dirname "$target_path" | xargs basename)
            local dst_data_file="$DST_DIR/data/$target_subdir/$target_hash"
            
            # Create data subdirectory if needed
            mkdir -p "$DST_DIR/data/$target_subdir"
            
            # Copy the data file if it doesn't exist
            if [ ! -f "$dst_data_file" ]; then
                cp "$target_path" "$dst_data_file"
            fi
            
            # Create the symlink
            ln -sf "../../data/$target_subdir/$target_hash" "$dst_file"
        else
            error "Symlink target '$target_path' does not exist for '$relative_path'"
        fi
    elif [ -f "$file_path" ]; then
        # It's a regular file, copy it
        cp "$file_path" "$dst_file"
    else
        error "Unknown file type for '$relative_path'"
    fi
}

# Main processing
info "Copying files from '$SRC_DIR' to '$DST_DIR'"

# Count total files for progress
total_files=$(find "$SRC_DIR/files" -type f -o -type l | wc -l)
current_file=0

# Process all files and symlinks in the files directory
while IFS= read -r -d '' file_path; do
    current_file=$((current_file + 1))
    
    # Calculate relative path from files directory
    relative_path="${file_path#$SRC_DIR/files/}"
    
    # Skip if it's the files directory itself
    if [ "$relative_path" = "" ]; then
        continue
    fi
    
    echo "[$current_file/$total_files] Copying: $relative_path"
    copy_file "$file_path" "$relative_path"
    
done < <(find "$SRC_DIR/files" -type f -o -type l -print0)

info "Copy complete! $total_files files processed."
info "Output directory: $DST_DIR"
