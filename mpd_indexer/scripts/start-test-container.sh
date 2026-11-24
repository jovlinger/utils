#!/bin/bash
# Start the mpd_indexer test container with the newest MPD checkout mounted.
# Runs recreate-bug then fixed prove (see test-container-entry.sh).
#
# Usage:
#   MPD_SRC=/path/to/jovlinger/MPD ./scripts/start-test-container.sh
#   INTERACTIVE=1 ...   # bash after prove
#   PROVE_IMAGE=debian:bookworm
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MPD_SRC="${MPD_SRC:-}"
IMAGE="${PROVE_IMAGE:-debian:bookworm}"
NAME="${TEST_CONTAINER_NAME:-mpd-dontwalk-test}"
ENTRY="$ROOT/scripts/test-container-entry.sh"

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
  echo "Set MPD_SRC to the dont-walk MPD checkout (newest Walk.cxx)." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon not available on this host." >&2
  exit 1
fi

chmod +x "$ENTRY"
echo "==> MPD_SRC=$MPD_SRC (newest) image=$IMAGE name=$NAME"

# Replace any prior instance of this named test container.
docker rm -f "$NAME" >/dev/null 2>&1 || true

exec docker run --rm --name "$NAME" \
  -e INTERACTIVE="${INTERACTIVE:-0}" \
  -v "$MPD_SRC:/src:ro" \
  -v "$ENTRY:/entry.sh:ro" \
  "$IMAGE" \
  bash /entry.sh
