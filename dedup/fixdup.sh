#!/bin/bash
# fixdup.sh - Repair files/ symlinks in a shasrv store.
#
# Usage: fixdup.sh {relative|absolute} <dedup_dir> [-v] [--dryrun]
#   relative  - rewrite links as relative paths into data/ (after moves in files/)
#   absolute  - rewrite links as absolute paths into data/

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

usage() {
    echo "Usage: $0 {relative|absolute} <dedup_dir> [-v] [--dryrun]" >&2
    echo "  relative  Rewrite files/ symlinks as relative paths into data/" >&2
    echo "  absolute  Rewrite files/ symlinks as absolute paths into data/" >&2
    exit 1
}

if [ $# -lt 2 ]; then
    usage
fi

STYLE="$1"
DEDUP_DIR="$2"
shift 2

case "$STYLE" in
    relative|absolute) ;;
    *) usage ;;
esac

if [ ! -f "$SCRIPT_DIR/env/bin/activate" ] && [ ! -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  echo "No venv at $SCRIPT_DIR/env or $SCRIPT_DIR/.venv." >&2
  echo "Run: $UTILS_ROOT/create_pipenv.sh dedup" >&2
  exit 1
fi
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  # Prefer project .venv when present (create_pipenv.sh layout).
  . "$SCRIPT_DIR/.venv/bin/activate"
else
  . "$SCRIPT_DIR/env/bin/activate"
fi

exec python "$SCRIPT_DIR/dedup.py" __fixdup__ "$STYLE" "$DEDUP_DIR" "$@"
