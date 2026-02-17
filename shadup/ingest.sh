#!/usr/bin/env bash
# Ingest files/dirs into hash-backed store with automatic rw/ro remount.
set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
INGEST_PY="$SCRIPT_DIR/ingest.py"
REMOUNT="$SCRIPT_DIR/with-ro-remounted-rw.sh"

err() { printf '[%s] ERROR: %s\n' "$(date -Is)" "$*" >&2; }

[ "$#" -gt 0 ] || {
  err "usage: $0 <file-or-dir> [...]"
  exit 2
}

command -v python3 >/dev/null || {
  err "missing python3"
  exit 1
}

[ -f "$INGEST_PY" ] || {
  err "missing $INGEST_PY"
  exit 1
}
[ -x "$REMOUNT" ] || {
  err "missing executable $REMOUNT"
  exit 1
}

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
  err "run with sudo"
  exit 1
fi

exec "$REMOUNT" python3 "$INGEST_PY" "$@"
