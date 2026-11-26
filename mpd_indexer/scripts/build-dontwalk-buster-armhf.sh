#!/bin/bash
# Host launcher: docker-run debian:buster + cross-compile dont-walk MPD.
#
# Usage:
#   MPD_SRC=/path/to/jovlinger/MPD ./scripts/build-dontwalk-buster-armhf.sh
#   # or via Makefile: make -C mpd_indexer build-dontwalk-armhf MPD_SRC=...
#
# Optional: BUILD_HOST=gmk.local  -- rsync sources + run docker on that host,
# then scp the binary back (gmk has docker + is closer to the lab).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT_DIR="${OUT_DIR:-$ROOT/out}"
INSIDE="$ROOT/scripts/build-dontwalk-inside-buster.sh"
MPD_SRC="${MPD_SRC:-}"
BUILD_HOST="${BUILD_HOST:-}"

if [ -z "$MPD_SRC" ]; then
  echo "MPD_SRC is required (checkout of jovlinger/MPD with dont-walk Walk.cxx)." >&2
  echo "Example: MPD_SRC=\$HOME/github.com/jovlinger/MPD" >&2
  exit 1
fi
if [ ! -f "$MPD_SRC/meson.build" ]; then
  echo "MPD_SRC=$MPD_SRC does not look like an MPD tree (no meson.build)." >&2
  exit 1
fi
if [ ! -f "$INSIDE" ]; then
  echo "missing $INSIDE" >&2
  exit 1
fi

mkdir -p "$OUT_DIR"
chmod +x "$INSIDE"

run_docker() {
  local src="$1"
  local out="$2"
  docker run --rm \
    -v "$src:/src:ro" \
    -v "$out:/out" \
    -v "$INSIDE:/inside.sh:ro" \
    debian:buster \
    bash /inside.sh
}

if [ -n "$BUILD_HOST" ]; then
  REMOTE_SRC="${REMOTE_MPD_SRC:-/tmp/mpd-dontwalk-src}"
  REMOTE_OUT="${REMOTE_OUT:-/tmp/mpd-buster-armhf-full}"
  echo "==> rsync MPD_SRC -> $BUILD_HOST:$REMOTE_SRC"
  ssh -o BatchMode=yes "$BUILD_HOST" "mkdir -p '$REMOTE_SRC' '$REMOTE_OUT'"
  rsync -az --delete \
    --exclude .git --exclude build --exclude .cache \
    "$MPD_SRC/" "$BUILD_HOST:$REMOTE_SRC/"
  scp -o BatchMode=yes "$INSIDE" "$BUILD_HOST:/tmp/build-dontwalk-inside-buster.sh"
  ssh -o BatchMode=yes "$BUILD_HOST" \
    "chmod +x /tmp/build-dontwalk-inside-buster.sh && \
     docker run --rm \
       -v '$REMOTE_SRC:/src:ro' \
       -v '$REMOTE_OUT:/out' \
       -v /tmp/build-dontwalk-inside-buster.sh:/inside.sh:ro \
       debian:buster bash /inside.sh"
  scp -o BatchMode=yes "$BUILD_HOST:$REMOTE_OUT/mpd" "$OUT_DIR/mpd"
else
  echo "==> local docker build (MPD_SRC=$MPD_SRC OUT=$OUT_DIR)"
  run_docker "$MPD_SRC" "$OUT_DIR"
fi

file "$OUT_DIR/mpd"
echo "OK wrote $OUT_DIR/mpd"
