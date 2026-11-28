#!/usr/bin/env bash
# tagflag -- remount wrapper for the song tag pipeline helper (tagflag.py).
#
# Blessed install:
#   ~/.local/bin/tagflag.sh   (this file -- the only remount layer)
#   ~/.local/bin/tagflag.py   (helper: postingest with remount disabled)
#   ~/.local/bin/tagflag -> tagflag.sh
#
# Usage:
#   tagflag
#   tagflag -f
#   tagflag -f "/mnt/sdb2/music/flac/files/Some Artist - Album"
#
# -f reprocesses all (force provider refetch + retag). Remount via
# with-ro-remounted-rw; postingest itself is not asked to remount.
#
set -Eeuo pipefail

SCRIPT_PATH="$(readlink -f "${BASH_SOURCE[0]}")"
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$SCRIPT_PATH")" && pwd)"
HELPER="$SCRIPT_DIR/tagflag.py"

# Resolve remount helper: env, PATH, or sibling bin checkout next to utils.
UTILS_ROOT="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd || true)"
if [[ -n "$UTILS_ROOT" && -d "$UTILS_ROOT/shadup" ]]; then
  BIN_DIR="$(cd "${JOVLINGER_BIN:-$UTILS_ROOT/../bin}" && pwd)"
else
  BIN_DIR="$(cd "${JOVLINGER_BIN:-$HOME/github.com/jovlinger/bin}" && pwd)"
fi
REMOUNT="${WITH_RO_REMOUNTED_RW:-$BIN_DIR/with-ro-remounted-rw.sh}"

if [[ "${1:-}" == "--install-local" ]]; then
  dest="${HOME}/.local/bin"
  mkdir -p "$dest"
  # Prefer source tree copies when this file is the binlink into shadup/.
  src_dir="$SCRIPT_DIR"
  if [[ ! -f "$src_dir/postingest" && -f "$HOME/github.com/jovlinger/utils/shadup/tagflag.sh" ]]; then
    src_dir="$HOME/github.com/jovlinger/utils/shadup"
  fi
  cp -f "$src_dir/tagflag.py" "$dest/tagflag.py"
  cp -f "$src_dir/tagflag.sh" "$dest/tagflag.sh"
  chmod +x "$dest/tagflag.py" "$dest/tagflag.sh"
  ln -sfn tagflag.sh "$dest/tagflag"
  if [[ -f "$src_dir/postingest" ]]; then
    printf '%s\n' "$src_dir/postingest" >"$dest/.tagflag-postingest"
  fi
  printf 'installed %s/{tagflag,tagflag.sh,tagflag.py}\n' "$dest"
  exit 0
fi

[[ -f "$HELPER" ]] || {
  printf 'tagflag: missing helper %s\n' "$HELPER" >&2
  exit 1
}
[[ -x "$REMOUNT" ]] || {
  printf 'tagflag: missing remount wrapper %s\n' "$REMOUNT" >&2
  exit 1
}

# Point helper at checkout postingest when installed under ~/.local/bin.
if [[ -f "$SCRIPT_DIR/postingest" ]]; then
  export TAGFLAG_POSTINGEST="$SCRIPT_DIR/postingest"
elif [[ -f "${HOME}/.local/bin/.tagflag-postingest" ]]; then
  export TAGFLAG_POSTINGEST="$(cat "${HOME}/.local/bin/.tagflag-postingest")"
fi

# Dry-run needs no remount; skip the outer remount layer.
for arg in "$@"; do
  if [[ "$arg" == "--dry-run" ]]; then
    export POSTINGEST_NO_REMOUNT=1
    exec "$HELPER" "$@"
  fi
done

exec "$REMOUNT" "$HELPER" "$@"
