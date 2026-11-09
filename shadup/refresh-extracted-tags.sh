#!/usr/bin/env bash
# Rebuild files/_meta and files/_tags browse mirrors (needs sudo remount).
#
# Blessed entry (utils/binlinks after `make -C shadup binlinks`):
#   refresh-extracted-tags
#   refresh-extracted-tags -v
#
# What this does:
#   1. Remounts $SHASRV_MNT (default /mnt/sdb2) read-write via with-ro-remounted-rw
#      (prompts for sudo unless already root).
#   2. Runs `shadup refresh-extracted-tags` against the store DB + shadir.
#   3. Remounts the volume read-only again.
#
# Defaults (override with env):
#   SHASRV_STORE_ROOT  /mnt/sdb2/music/flac
#   SHASRV_DB          $HOME/Music/shasrv/shadup.db
#   SHASRV_MNT         /mnt/sdb2   (used by with-ro-remounted-rw)
#
# This only rebuilds symlink mirrors from tags already in the shadup DB.
# It does NOT run musicscan, combine, or importtags. For the full tag path
# after albums are already under files/, use `postingest` (also remounts).
#
# Mirror layout (intentional cycles):
#   _meta/<album>/album              -> real album dir
#   _meta/<album>/<tag_path>         -> _tags/<tag_path>
#   _tags/<tag_path>/<album>         -> _meta/<album>
#
set -Eeuo pipefail

SHADUP_DIR="$(CDPATH= cd -- "$(dirname -- "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
UTILS_ROOT="$(cd "$SHADUP_DIR/.." && pwd)"
BIN_DIR="$(cd "${JOVLINGER_BIN:-$UTILS_ROOT/../bin}" && pwd)"
REMOUNT="${WITH_RO_REMOUNTED_RW:-$BIN_DIR/with-ro-remounted-rw.sh}"
SHADUP_CLI="$SHADUP_DIR/shadup"

STORE_ROOT="${SHASRV_STORE_ROOT:-/mnt/sdb2/music/flac}"
DB_PATH="${SHASRV_DB:-$HOME/Music/shasrv/shadup.db}"

err() { printf '[%s] ERROR: %s\n' "$(date -Is)" "$*" >&2; }

[ -x "$REMOUNT" ] || {
  err "missing executable $REMOUNT"
  exit 1
}
[ -x "$SHADUP_CLI" ] || {
  err "missing executable $SHADUP_CLI"
  exit 1
}
[ -f "$DB_PATH" ] || {
  err "missing shadup DB: $DB_PATH (set SHASRV_DB)"
  exit 1
}
[ -d "$STORE_ROOT" ] || {
  err "missing store root: $STORE_ROOT (set SHASRV_STORE_ROOT)"
  exit 1
}

exec "$REMOUNT" "$SHADUP_CLI" \
  --shadir "$STORE_ROOT" \
  --db "$DB_PATH" \
  "$@" \
  refresh-extracted-tags
