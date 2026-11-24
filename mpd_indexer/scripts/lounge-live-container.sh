#!/bin/bash
# Live gmk lounge enqueue, inside Docker. Not part of make test.
#
#   ./scripts/lounge-live-container.sh
#
# Mounts 192.168.88.40:/mnt/sdb2/music/flac (the tree SHD serves as NAS/gmk)
# and runs the in-repo resolver on files/_tags/genre/lounge.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
UTILS="$(cd "$ROOT/.." && pwd)"
RESOLVER="$UTILS/volumio_scanfolder_mpdignore/mpdignore.js"
CHECK="$ROOT/scripts/lounge-live-check.js"
IMAGE="${LOUNGE_IMAGE:-node:20-bookworm}"
ADDR="${GMK_NFS_ADDR:-192.168.88.40}"
EXPORT="${GMK_NFS_EXPORT:-/mnt/sdb2/music/flac}"
VOL="${GMK_VOLUME:-gmk-flac-live}"
NAME="mpd-lounge-live-$$"

if [ ! -f "$RESOLVER" ] || [ ! -f "$CHECK" ]; then
  echo "Missing resolver or check script." >&2
  exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker daemon not available." >&2
  exit 1
fi

docker volume create --driver local \
  --opt type=nfs \
  --opt "o=addr=${ADDR},ro,vers=4" \
  --opt "device=:${EXPORT}" \
  "$VOL" >/dev/null

echo "==> docker run --rm -v ${VOL}:/mnt/gmk:ro ${IMAGE} node /check.js"
echo "==> nfs ${ADDR}:${EXPORT}"
docker run --rm --name "$NAME" \
  -v "${VOL}:/mnt/gmk:ro" \
  -v "$RESOLVER:/resolver/mpdignore.js:ro" \
  -v "$CHECK:/check.js:ro" \
  "$IMAGE" \
  node /check.js
