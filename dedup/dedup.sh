#!/bin/bash
# shasrv wrapper - content-addressed file storage with mount detection.
#
# Detects if the target filesystem is mounted read-only; if so, remounts it
# read-write before running dedup.py, and always remounts read-only on exit.
#
# Usage: same as dedup.py (all arguments are passed through)
#   dedup.sh <sources...> <target_dir> [-v] [--dryrun] [--remove-source]
#
# Symlink repair: use fixdup.sh {relative|absolute} <dedup_dir> ...

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ ! -f "$SCRIPT_DIR/env/bin/activate" ] && [ ! -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  echo "No venv at $SCRIPT_DIR/env or $SCRIPT_DIR/.venv." >&2
  echo "Run: $UTILS_ROOT/create_pipenv.sh dedup" >&2
  exit 1
fi
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  . "$SCRIPT_DIR/.venv/bin/activate"
else
  . "$SCRIPT_DIR/env/bin/activate"
fi

REMOUNTED=false
MOUNT_POINT=""

log(){ printf '[shasrv] %s\n' "$*" >&2; }

# Find the mount point for a given path
get_mount_point() {
    findmnt -n -o TARGET --target "$1" 2>/dev/null | head -1
}

# Check if a path is on a read-only filesystem
is_readonly() {
    local opts
    opts=$(findmnt -n -o OPTIONS --target "$1" 2>/dev/null | head -1)
    echo "$opts" | grep -qw 'ro'
}

cleanup() {
    if $REMOUNTED && [ -n "$MOUNT_POINT" ]; then
        log "remounting $MOUNT_POINT read-only"
        mount -o remount,ro "$MOUNT_POINT" 2>/dev/null || true
    fi
}
trap cleanup EXIT INT TERM

# Dedup mode: last positional is the target
TARGET_DIR=""
positionals=()
for arg in "$@"; do
    case "$arg" in
        -v|--verbose|--dryrun|--remove-source) ;;
        *)           positionals+=("$arg") ;;
    esac
done

if [ ${#positionals[@]} -ge 1 ]; then
    TARGET_DIR="${positionals[-1]}"
fi

# If we found a target, check its mount status
if [ -n "$TARGET_DIR" ]; then
    # Resolve to an existing path (target or its parent)
    check_path="$TARGET_DIR"
    while [ ! -e "$check_path" ] && [ "$check_path" != "/" ]; do
        check_path="$(dirname "$check_path")"
    done

    if [ -e "$check_path" ] && is_readonly "$check_path"; then
        MOUNT_POINT="$(get_mount_point "$check_path")"
        if [ -n "$MOUNT_POINT" ]; then
            log "target is on read-only filesystem ($MOUNT_POINT), remounting rw"
            mount -o remount,rw "$MOUNT_POINT"
            REMOUNTED=true
        fi
    fi
fi

# Run the Python deduplication script
python "$SCRIPT_DIR/dedup.py" "$@"
