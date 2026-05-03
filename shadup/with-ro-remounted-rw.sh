#!/usr/bin/env bash
# Remount SHASRV_MNT rw, run <command> [args...] as the current user, then remount ro.
# Privileged steps use sudo when not root (typically: sudo mount -o remount,...).
#
# Usage: ~/shadup/with-ro-remounted-rw.sh <command> [args...]
set -Eeuo pipefail
MNT="${SHASRV_MNT:-/mnt/sdb2}"

log(){ printf '[%s] %s\n' "$(date -Is)" "$*" >&2; }
err(){ log "ERROR: $*"; }

# Run a command with the privileges needed for mount(8) (root, or sudo when non-root).
priv() {
  if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    "$@"
  else
    sudo "$@"
  fi
}

need_tools() {
  local x
  for x in findmnt awk mount; do
    command -v "$x" >/dev/null || {
      err "missing tool: $x"
      exit 1
    }
  done
  if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    command -v sudo >/dev/null || {
      err "missing sudo (needed to remount $MNT when not root)"
      exit 1
    }
  fi
}

get_real_mount() {
  findmnt -R -n -o SOURCE,FSTYPE,OPTIONS -- "$MNT" 2>/dev/null | awk '$2!="autofs"{print; exit}'
}

remount_mode() {
  local mode="$1"
  local line src fstype

  # Prefer mountpoint-only remount (util-linux). Device+target remount is flaky on
  # some setups; the old fallback `mount -t fstype -o ro src mnt` is a *new* mount
  # and fails with "already mounted" while leaving the fs rw.
  if priv mount -o "remount,$mode" "$MNT"; then
    return 0
  fi

  line="$(get_real_mount || true)"
  src="$(printf '%s' "$line" | awk '{print $1}')"
  fstype="$(printf '%s' "$line" | awk '{print $2}')"
  [ -n "$src" ] && [ -n "$fstype" ] || {
    err "cannot resolve real mount beneath $MNT (needed for remount,$mode)"
    return 1
  }
  priv mount -o "remount,$mode" --source "$src" --target "$MNT"
}

cleanup() {
  local rc="$?"
  trap - EXIT INT TERM HUP QUIT PIPE
  log "remount ro: $MNT"
  if ! remount_mode ro; then
    err "filesystem may still be read-write — fix manually: sudo mount -o remount,ro $MNT"
  fi
  exit "$rc"
}

[ "$#" -ge 1 ] || { echo "usage: $0 <command> [args...]" >&2; exit 2; }
need_tools

# Trap first so any exit (including failed remount rw) runs cleanup and remounts ro.
trap cleanup EXIT INT TERM HUP QUIT PIPE

log "remount rw: $MNT"
remount_mode rw

"$@"
