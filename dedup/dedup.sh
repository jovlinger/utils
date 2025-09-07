#!/bin/bash
# Shell wrapper for the file deduplication utility

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run the Python deduplication script
python3 "$SCRIPT_DIR/dedup.py" "$@"
