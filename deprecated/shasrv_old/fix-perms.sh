#!/usr/bin/env bash
set -Eeuo pipefail
MNT="/mnt/sdb2"
DATA_DIR="/mnt/sdb2/music/flac/data"
log(){ printf '[%s] %s\n' "$(date -Is)" "$*"; }
err(){ printf '[%s] ERROR: %s\n' "$(date -Is)" "$*" >&2; }
trap 'rc=$?; log "remount ro"; mount -o remount,ro "$MNT" || true; exit $rc' EXIT INT TERM

[ -d "$DATA_DIR" ] || { err "missing $DATA_DIR"; exit 1; }

log "remount rw"
mount -o remount,rw "$MNT"

log "scanning non-0644 files and non-0755 dirs under $DATA_DIR"
FILES_BAD=$(find "$DATA_DIR" -xdev -type f ! -perm 0644 | wc -l || echo 0)
DIRS_BAD=$(find "$DATA_DIR" -xdev -type d ! -perm 0755 | wc -l || echo 0)
log "will fix: files=$FILES_BAD dirs=$DIRS_BAD"

log "chmod files -> 0644"
find "$DATA_DIR" -xdev -type f ! -perm 0644 -exec chmod 0644 {} +

log "chmod dirs  -> 0755"
find "$DATA_DIR" -xdev -type d ! -perm 0755 -exec chmod 0755 {} +

log "done"
