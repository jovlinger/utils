#!/bin/bash
# Build dont-walk MPD in a container and prove _tags is indexed under a
# SHD-like nested path (NAS/gmk/files), with files/.mpdignore = _meta only.
#
# Usage (from utils/mpd_indexer or anywhere):
#   MPD_SRC=/path/to/jovlinger/MPD ./scripts/prove-dontwalk-tags-container.sh
#
# Exit 0 only if: songs stay unique, lsinfo shows _tags/album/..., and
# _meta is absent from lsinfo of files/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MPD_SRC="${MPD_SRC:-}"
IMAGE="${PROVE_IMAGE:-debian:bookworm}"
NAME="mpd-dontwalk-prove-$$"

if [ -z "$MPD_SRC" ]; then
  for cand in \
    "$HOME/github.com/jovlinger/MPD" \
    /Users/johan/github.com/jovlinger/MPD
  do
    if [ -f "$cand/src/db/update/Walk.cxx" ]; then
      MPD_SRC="$cand"
      break
    fi
  done
fi
if [ -z "$MPD_SRC" ] || [ ! -f "$MPD_SRC/meson.build" ]; then
  echo "Set MPD_SRC to the dont-walk MPD checkout." >&2
  exit 1
fi

echo "==> MPD_SRC=$MPD_SRC image=$IMAGE"

docker run --rm --name "$NAME" \
  -v "$MPD_SRC:/src:ro" \
  -v "$ROOT/scripts/prove-dontwalk-tags-inside.sh:/inside.sh:ro" \
  "$IMAGE" \
  bash /inside.sh
