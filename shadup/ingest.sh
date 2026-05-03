#!/usr/bin/env bash
# Ingest files/dirs into hash-backed store with automatic rw/ro remount.
# 
#
# Usage:
#   ./ingest.sh public/albumdir1 public/albumdir2 ...
#   ./ingest.sh public/albumdir*          # shell glob; one arg per album
#
# Remounting the store filesystem uses sudo mount only when you are not root
# (see with-ro-remounted-rw.sh). The ingest Python process runs as your user.
#
# Each directory arg's basename becomes the dest_prefix under files/,
# so  public/MyAlbum  →  files/MyAlbum/<track>  (symlink to data/<shard>/<sha>).
#
# CAUTION: Do NOT pass the top-level parent directory (e.g. "public").
#   ./ingest.sh public                    # WRONG
# This would set dest_prefix="public", creating files/public/albumdir/track
# instead of the intended files/albumdir/track — an unwanted extra level.
# It also ingests (and deletes from source!) ALL files under public/.
#
# Recovery if you did this by mistake:
#   Data blobs in data/ are safe. Fix the symlink tree with:
#     mv /mnt/sdb2/music/flac/files/public/* /mnt/sdb2/music/flac/files/
#     rmdir /mnt/sdb2/music/flac/files/public




set -Eeuo pipefail

# Real utils/shadup directory (resolves e.g. ~/ingest.sh → .../utils/shadup/ingest.sh).
SHADUP_DIR="$(CDPATH= cd -- "$(dirname -- "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
UTILS_ROOT="$(cd "$SHADUP_DIR/.." && pwd)"
INGEST_PY="$SHADUP_DIR/ingest.py"
REMOUNT="$SHADUP_DIR/with-ro-remounted-rw.sh"

err() { printf '[%s] ERROR: %s\n' "$(date -Is)" "$*" >&2; }

[ "$#" -gt 0 ] || {
  err "usage: $0 <file-or-dir> [...]"
  exit 2
}

# ingest.py runs shadup.py with sys.executable, so we must exec the venv interpreter
# by path — not `python` on PATH. The remount wrapper runs "$@" without sudo.
# The ./shadup → pylauncher symlink is for CLI shadup.py only.
SHADUP_VENV=""
if [ -f "$SHADUP_DIR/env/bin/activate" ]; then
  SHADUP_VENV="$SHADUP_DIR/env"
elif [ -f "$SHADUP_DIR/.venv/bin/activate" ]; then
  SHADUP_VENV="$SHADUP_DIR/.venv"
else
  err "No venv under $SHADUP_DIR (expected env/ or .venv/)."
  err "Run: $UTILS_ROOT/create_pipenv.sh shadup   or   $SHADUP_DIR/setup-venv.sh"
  exit 1
fi
if [ -x "$SHADUP_VENV/bin/python" ]; then
  SHADUP_PYTHON="$SHADUP_VENV/bin/python"
elif [ -x "$SHADUP_VENV/bin/python3" ]; then
  SHADUP_PYTHON="$SHADUP_VENV/bin/python3"
else
  err "No python or python3 in $SHADUP_VENV/bin"
  exit 1
fi

[ -f "$INGEST_PY" ] || {
  err "missing $INGEST_PY"
  exit 1
}
[ -x "$REMOUNT" ] || {
  err "missing executable $REMOUNT"
  exit 1
}

exec "$REMOUNT" "$SHADUP_PYTHON" "$INGEST_PY" "$@"
