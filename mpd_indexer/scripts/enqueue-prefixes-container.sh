#!/bin/bash
# Docker e2e: dont-walk MPD indexes the multi-album fixture, tag prefixes
# have no file rows, and the in-repo resolver matches the canonical sets.
#
# Not part of `make test`.
#   MPD_SRC=/path/to/jovlinger/MPD ./scripts/enqueue-prefixes-container.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UTILS="$(cd "$ROOT/.." && pwd)"
MPD_SRC="${MPD_SRC:-}"
IMAGE="${PROVE_IMAGE:-debian:bookworm}"
NAME="mpd-enqueue-prefix-$$"
RESOLVER="$UTILS/volumio_scanfolder_mpdignore/mpdignore.js"

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
if [ ! -f "$RESOLVER" ]; then
  echo "Missing resolver: $RESOLVER" >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon not available." >&2
  exit 1
fi

echo "==> MPD_SRC=$MPD_SRC image=$IMAGE"
docker run --rm --name "$NAME" \
  -v "$MPD_SRC:/src:ro" \
  -v "$ROOT/scripts/enqueue-prefixes-inside.sh:/inside.sh:ro" \
  -v "$RESOLVER:/resolver/mpdignore.js:ro" \
  "$IMAGE" \
  bash /inside.sh
