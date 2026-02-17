#!/bin/bash

# fixdup.sh - Fix symlinks in dedup filesystems
# Usage: fixdup.sh <dedup_dir>
#   dedup_dir: Dedup directory (with data/ and files/ subdirectories)
#
# This utility fixes symlinks that use relative paths by converting them to absolute paths.
# It handles both:
# 1. Files that were moved before transitioning to absolute paths
# 2. Whole filesystems that still use relative links

set -euo pipefail

# Function to display usage
usage() {
    echo "Usage: $0 <dedup_dir>"
    echo "  dedup_dir: Dedup directory (with data/ and files/ subdirectories)"
    echo ""
    echo "This utility fixes symlinks that use relative paths by converting them to absolute paths."
    echo "It reconstructs the correct absolute path using the last two components of the relative path."
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
if [ $# -ne 1 ]; then
    usage
fi

DEDUP_DIR="$(realpath "$1")"

# Validate dedup directory exists
if [ ! -d "$DEDUP_DIR" ]; then
    error "Dedup directory '$DEDUP_DIR' does not exist"
fi

# Check for required subdirectories
if [ ! -d "$DEDUP_DIR/data" ]; then
    error "Dedup directory '$DEDUP_DIR' does not contain a 'data' subdirectory"
fi

if [ ! -d "$DEDUP_DIR/files" ]; then
    error "Dedup directory '$DEDUP_DIR' does not contain a 'files' subdirectory"
fi

# Function to fix a single symlink
fix_symlink() {
    local symlink_path="$1"
    local current_target
    current_target=$(readlink "$symlink_path")
    
    # Skip if already absolute path
    if [[ "$current_target" == /* ]]; then
        return 0
    fi
    
    # Extract the last two components from the relative path
    # e.g., "../../data/ab/abc123..." -> "ab/abc123..."
    local last_two_components
    last_two_components=$(echo "$current_target" | sed 's|.*/data/||')
    
    # Construct the new absolute path
    local new_target="$DEDUP_DIR/data/$last_two_components"
    
    # Verify the target file exists
    if [ ! -f "$new_target" ]; then
        echo "Warning: Target file '$new_target' does not exist for symlink '$symlink_path'"
        return 1
    fi
    
    # Remove the old symlink and create a new one with absolute path
    rm "$symlink_path"
    ln -s "$new_target" "$symlink_path"
    
    echo "Fixed: $symlink_path -> $new_target"
    return 0
}

# Main processing
info "Fixing symlinks in '$DEDUP_DIR'"

# Count total symlinks for progress
total_symlinks=$(find "$DEDUP_DIR/files" -type l | wc -l)
current_symlink=0
fixed_count=0
skipped_count=0
error_count=0

# Process all symlinks in the files directory
while IFS= read -r -d '' symlink_path; do
    current_symlink=$((current_symlink + 1))
    
    echo "[$current_symlink/$total_symlinks] Processing: ${symlink_path#$DEDUP_DIR/files/}"
    
    if fix_symlink "$symlink_path"; then
        if [[ "$(readlink "$symlink_path")" == /* ]]; then
            skipped_count=$((skipped_count + 1))
        else
            fixed_count=$((fixed_count + 1))
        fi
    else
        error_count=$((error_count + 1))
    fi
    
done < <(find "$DEDUP_DIR/files" -type l -print0)

info "Fix complete!"
info "  Total symlinks: $total_symlinks"
info "  Fixed: $fixed_count"
info "  Already absolute: $skipped_count"
info "  Errors: $error_count"

if [ $error_count -gt 0 ]; then
    exit 1
fi
