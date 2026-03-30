#!/usr/bin/env bash
# Ingest files/dirs into hash-backed store with automatic rw/ro remount.
# 
#
# Usage:
#   sudo ./ingest.sh public/albumdir1 public/albumdir2 ...
#   sudo ./ingest.sh public/albumdir*          # shell glob; one arg per album
#
# Each directory arg's basename becomes the dest_prefix under files/,
# so  public/MyAlbum  →  files/MyAlbum/<track>  (symlink to data/<shard>/<sha>).
#
# CAUTION: Do NOT pass the top-level parent directory (e.g. "public").
#   sudo ./ingest.sh public                    # WRONG
# This would set dest_prefix="public", creating files/public/albumdir/track
# instead of the intended files/albumdir/track — an unwanted extra level.
# It also ingests (and deletes from source!) ALL files under public/.
#
# Recovery if you did this by mistake:
#   Data blobs in data/ are safe. Fix the symlink tree with:
#     mv /mnt/sdb2/music/flac/files/public/* /mnt/sdb2/music/flac/files/
#     rmdir /mnt/sdb2/music/flac/files/public




set -Eeuo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
INGEST_PY="$SCRIPT_DIR/ingest.py"
REMOUNT="$SCRIPT_DIR/with-ro-remounted-rw.sh"

err() { printf '[%s] ERROR: %s\n' "$(date -Is)" "$*" >&2; }

[ "$#" -gt 0 ] || {
  err "usage: $0 <file-or-dir> [...]"
  exit 2
}

if [ ! -f "$SCRIPT_DIR/env/bin/activate" ]; then
  err "No venv at $SCRIPT_DIR/env."
  err "Run: $UTILS_ROOT/create_pipenv.sh shadup"
  exit 1
fi
. "$SCRIPT_DIR/env/bin/activate"

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

exec "$REMOUNT" python "$INGEST_PY" "$@"
