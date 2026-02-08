#!/usr/bin/env bash
# Usage: sudo ~/shasrv/with-ro-remounted-rw <command> [args...]
set -Eeuo pipefail
MNT="/mnt/sdb2"
log(){ printf '[%s] %s\n' "$(date -Is)" "$*" >&2; }

[ "$#" -ge 1 ] || { echo "usage: $0 <command> [args...]" >&2; exit 2; }
log "remount rw: $MNT"
mount -o remount,rw "$MNT"
trap 'rc=$?; log "remount ro: /mnt/sdb2"; mount -o remount,ro /mnt/sdb2 || true; exit $rc' EXIT INT TERM
exec "$@"
