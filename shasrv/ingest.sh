#!/usr/bin/env bash
# Ingest files/dirs into hash-backed store on /mnt/sdb2/music/flac
# - One line per file: "Doing: files/<dest_prefix>/<rel>"
# - Direct write to SD (no temp on SD). Verify hash, then chmod 0644
# - Remove source only on success
# - Auto-detect real f2fs beneath autofs and ensure rw at start; ALWAYS remount ro on exit
# - Process files in deterministic, version-aware name order

set -Eeuo pipefail
shopt -s nullglob

STORE_ROOT="/mnt/sdb2/music/flac"
DATA_DIR="$STORE_ROOT/data"
FILES_DIR="$STORE_ROOT/files"
MNT="/mnt/sdb2"

err(){ printf '[%s] ERROR: %s\n' "$(date -Is)" "$*" >&2; }
need_tools(){ for x in sha256sum realpath mv cp ln mkdir rmdir stat findmnt awk grep sort; do command -v "$x" >/dev/null || { err "missing $x"; exit 1; }; done; }

get_real_mount(){ findmnt -R -n -o SOURCE,FSTYPE,OPTIONS -- "$MNT" 2>/dev/null | awk '$2!="autofs"{print; exit}'; }

cleanup(){
  # Always remount the real filesystem ro on exit
  local line src fstype
  line="$(get_real_mount || true)"; src="$(printf '%s' "$line" | awk '{print $1}')"; fstype="$(printf '%s' "$line" | awk '{print $2}')"
  if [ -n "$src" ] && [ -n "$fstype" ]; then
    mount -o remount,ro "$src" "$MNT" 2>/dev/null || mount -t "$fstype" -o ro "$src" "$MNT" 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

[ -d "$DATA_DIR" ] && [ -d "$FILES_DIR" ] || { err "store layout missing under $STORE_ROOT"; exit 1; }
[ "$#" -gt 0 ] || { err "usage: $0 <file-or-dir> [...]"; exit 2; }
need_tools
[ "${EUID:-$(id -u)}" -eq 0 ] || { err "run with sudo"; exit 1; }

ensure_real_rw(){
  local line src fstype opts
  line="$(get_real_mount || true)"; src="$(printf '%s' "$line" | awk '{print $1}')"; fstype="$(printf '%s' "$line" | awk '{print $2}')"; opts="$(printf '%s' "$line" | awk '{print $3}')"
  [ -n "$src" ] && [ -n "$fstype" ] || { err "cannot resolve real mount"; exit 1; }
  printf '%s' "$opts" | grep -q '\<rw\>' && return 0
  mount -o remount,rw "$src" "$MNT" 2>/dev/null || mount -t "$fstype" -o rw "$src" "$MNT" || { err "remount failed"; exit 1; }
}

ensure_real_rw

hash_file(){ sha256sum -- "$1" | awk '{print $1}'; }

write_payload(){
  local src="$1" sha="$2" shard dst_dir dst newsha
  shard="${sha:0:2}"; dst_dir="$DATA_DIR/$shard"; dst="$dst_dir/$sha"
  [ -e "$dst" ] && { echo "$dst"; return 0; }
  mkdir -p "$dst_dir"
  cp -f -- "$src" "$dst" || { rm -f -- "$dst" 2>/dev/null || true; return 1; }
  newsha="$(sha256sum -- "$dst" | awk '{print $1}')"
  [ "$newsha" = "$sha" ] || { rm -f -- "$dst" 2>/dev/null || true; return 1; }
  chmod 0644 "$dst" || true
  echo "$dst"
}

link_into_files(){
  local src_root="$1" src_path="$2" payload="$3" dest_prefix="$4" rel link_path link_dir rel_target
  rel="${src_path#"$src_root"/}"; [ -n "$dest_prefix" ] && link_path="$FILES_DIR/$dest_prefix/$rel" || link_path="$FILES_DIR/$rel"
  link_dir="$(dirname -- "$link_path")"; mkdir -p "$link_dir"
  rel_target="$(realpath --relative-to="$link_dir" "$payload")"; ln -sfn "$rel_target" "$link_path"
}

ingest_one(){
  local src="$1" src_root="$2" dest_prefix="$3" sha payload rel
  [ -f "$src" ] || return 0
  rel="${src#"$src_root"/}"; printf 'Doing: files/%s%s\n' "${dest_prefix:+$dest_prefix/}" "$rel" >&2
  sha="$(hash_file "$src")" || { err "hash failed: $src"; return 1; }
  payload="$(write_payload "$src" "$sha")" || { err "copy failed: $src"; return 1; }
  link_into_files "$src_root" "$src" "$payload" "$dest_prefix" || { err "link failed: $src"; return 1; }
  rm -f -- "$src" || { err "remove failed: $src"; return 1; }
}

walk_arg(){
  local arg="$1" abs base
  abs="$(realpath -- "$arg")"
  if [ -f "$abs" ]; then
    base="$(basename -- "$(dirname -- "$abs")")"; ingest_one "$abs" "$(dirname -- "$abs")" "$base"
  elif [ -d "$abs" ]; then
    base="$(basename -- "$abs")"
    # process files in version-aware sorted name order
    ( cd "$abs" && find . -type f -printf '%P\0' | LC_ALL=C sort -z -V ) | while IFS= read -r -d '' rel; do
      ingest_one "$abs/$rel" "$abs" "$base" || true
    done
    while IFS= read -r -d '' d; do rmdir "$d" 2>/dev/null || true; done < <(find "$abs" -depth -type d -print0)
  else
    err "not found: $arg"
  fi
}

for a in "$@"; do walk_arg "$a"; done
