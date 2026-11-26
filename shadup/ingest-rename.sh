#!/usr/bin/env bash
# Store-side album rename from tag/cue consensus (ingest_rename).
#
# Blessed entry (utils/binlinks):
#   ingest-rename --dry-run                 # print only
#   ingest-rename                           # remount rw, shadup mv each RENAME
#   ingest-rename --dry-run --album 'junk basename here'
#   ingest-rename --album 'junk basename here'
#
# Bare run writes; pass --dry-run to preview. This wrapper remounts via
# with-ro-remounted-rw when not in --dry-run mode.
set -Eeuo pipefail

SHADUP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UTILS_ROOT="$(cd "$SHADUP_DIR/.." && pwd)"
BIN_DIR="$(cd "${JOVLINGER_BIN:-$UTILS_ROOT/../bin}" && pwd)"
REMOUNT="${WITH_RO_REMOUNTED_RW:-$BIN_DIR/with-ro-remounted-rw.sh}"
RENAME_PY="$SHADUP_DIR/ingest-rename.py"

err() { printf '[%s] ERROR: %s\n' "$(date -Is)" "$*" >&2; }

SHADUP_VENV=""
VENV_RESOLVE="$UTILS_ROOT/lib/venv-resolve.sh"
if [ -f "$VENV_RESOLVE" ]; then
  # shellcheck source=/dev/null
  . "$VENV_RESOLVE"
  resolve_utils_venv "$SHADUP_DIR" "$UTILS_ROOT"
  SHADUP_VENV="$VENV_DIR"
else
  for name in .venv venv env; do
    if [ -f "$SHADUP_DIR/$name/bin/activate" ]; then
      SHADUP_VENV="$SHADUP_DIR/$name"
      break
    fi
  done
fi
if [ -z "${SHADUP_VENV:-}" ]; then
  err "No venv under $SHADUP_DIR"
  exit 1
fi
if [ -x "$SHADUP_VENV/bin/python3" ]; then
  SHADUP_PYTHON="$SHADUP_VENV/bin/python3"
elif [ -x "$SHADUP_VENV/bin/python" ]; then
  SHADUP_PYTHON="$SHADUP_VENV/bin/python"
else
  err "No python in $SHADUP_VENV/bin"
  exit 1
fi

[ -f "$RENAME_PY" ] || {
  err "missing $RENAME_PY"
  exit 1
}

dry_run=0
for arg in "$@"; do
  if [ "$arg" = "--dry-run" ]; then
    dry_run=1
    break
  fi
done

if [ "$dry_run" -eq 0 ]; then
  [ -x "$REMOUNT" ] || {
    err "missing executable $REMOUNT (needed when not --dry-run)"
    exit 1
  }
  exec "$REMOUNT" "$SHADUP_PYTHON" "$RENAME_PY" "$@"
fi

exec "$SHADUP_PYTHON" "$RENAME_PY" "$@"
