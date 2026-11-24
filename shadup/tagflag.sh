#!/usr/bin/env bash
# tagflag -- full musicology/tag/import/_tags pipeline (wrapper around postingest).
#
# Blessed install (also linked from utils/binlinks after make -C shadup binlinks):
#   ~/.local/bin/tagflag.sh
#   ~/.local/bin/tagflag.py
#   ~/.local/bin/tagflag -> tagflag.sh
#
# Usage:
#   tagflag
#   tagflag -f
#   tagflag -f "/mnt/sdb2/music/flac/files/Some Artist - Album"
#
# -f reprocesses all (force provider refetch + retag). Remount is inside postingest.
# Install copies only the wrappers; postingest is resolved from the utils tree
# (or TAGFLAG_POSTINGEST / PATH).
#
set -Eeuo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)"
PY="$SCRIPT_DIR/tagflag.py"

if [[ "${1:-}" == "--install-local" ]]; then
  dest="${HOME}/.local/bin"
  mkdir -p "$dest"
  cp -f "$SCRIPT_DIR/tagflag.py" "$dest/tagflag.py"
  cp -f "$SCRIPT_DIR/tagflag.sh" "$dest/tagflag.sh"
  chmod +x "$dest/tagflag.py" "$dest/tagflag.sh"
  ln -sfn tagflag.sh "$dest/tagflag"
  # Point installed py at this checkout's postingest when not on PATH.
  if [[ -f "$SCRIPT_DIR/postingest" ]]; then
    printf '%s\n' "$SCRIPT_DIR/postingest" >"$dest/.tagflag-postingest"
  fi
  printf 'installed %s/{tagflag,tagflag.sh,tagflag.py}\n' "$dest"
  exit 0
fi

[ -f "$PY" ] || {
  printf 'tagflag: missing %s\n' "$PY" >&2
  exit 1
}

# Prefer a sibling postingest, else the path recorded at --install-local.
if [[ -f "$SCRIPT_DIR/postingest" ]]; then
  export TAGFLAG_POSTINGEST="$SCRIPT_DIR/postingest"
elif [[ -f "${HOME}/.local/bin/.tagflag-postingest" ]]; then
  export TAGFLAG_POSTINGEST="$(cat "${HOME}/.local/bin/.tagflag-postingest")"
fi

exec "$PY" "$@"
