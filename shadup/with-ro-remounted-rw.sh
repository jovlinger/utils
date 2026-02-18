#!/usr/bin/env bash
# Usage: sudo ~/shadup/with-ro-remounted-rw.sh <command> [args...]
set -Eeuo pipefail
MNT="${SHASRV_MNT:-/mnt/sdb2}"

log(){ printf '[%s] %s\n' "$(date -Is)" "$*" >&2; }
err(){ log "ERROR: $*"; }

need_tools() {
  local x
  for x in findmnt awk mount; do
    command -v "$x" >/dev/null || {
      err "missing tool: $x"
      exit 1
    }
  done
}

get_real_mount() {
  findmnt -R -n -o SOURCE,FSTYPE,OPTIONS -- "$MNT" 2>/dev/null | awk '$2!="autofs"{print; exit}'
}

remount_mode() {
  local mode="$1"
  local line src fstype
  line="$(get_real_mount || true)"
  src="$(printf '%s' "$line" | awk '{print $1}')"
  fstype="$(printf '%s' "$line" | awk '{print $2}')"
  [ -n "$src" ] && [ -n "$fstype" ] || {
    err "cannot resolve real mount beneath $MNT"
    return 1
  }
  mount -o "remount,$mode" "$src" "$MNT" 2>/dev/null || mount -t "$fstype" -o "$mode" "$src" "$MNT"
}

cleanup() {
  local rc="$?"
  trap - EXIT INT TERM HUP QUIT PIPE
  log "remount ro: $MNT"
  remount_mode ro || true
  exit "$rc"
}

[ "$#" -ge 1 ] || { echo "usage: $0 <command> [args...]" >&2; exit 2; }
need_tools

# Trap first so any exit (including failed remount rw) runs cleanup and remounts ro.
trap cleanup EXIT INT TERM HUP QUIT PIPE

log "remount rw: $MNT"
remount_mode rw

"$@"
