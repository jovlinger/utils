#!/bin/sh
# Copy run-with-stdout-logged.py from sister repo thermo/onboard into git-ignored
# .docker-import/ so the DMZ Dockerfile can COPY it (build context is thermo/dmz only).
set -eu

DMZ="$(cd "$(dirname "$0")" && pwd)"
SRC="$DMZ/../onboard/run-with-stdout-logged.py"
DST="$DMZ/.docker-import/run-with-stdout-logged.py"

mkdir -p "$DMZ/.docker-import"
if [ ! -f "$SRC" ]; then
	echo "dmz: missing log wrapper: $SRC" >&2
	echo "  Expected ../onboard/run-with-stdout-logged.py (sister repo next to thermo/dmz)." >&2
	exit 1
fi
cp "$SRC" "$DST"
