#!/bin/sh
# Copy run-with-stdout-logged.py from the bin repo (sibling of utils/) into git-ignored
# .docker-import/ so the DMZ Dockerfile can COPY it (build context is thermo/dmz only).
# Override: DMZ_RUN_WITH_SRC=/absolute/path/to/run-with-stdout-logged.py
set -eu

DMZ="$(cd "$(dirname "$0")" && pwd)"
SRC="${DMZ_RUN_WITH_SRC:-$DMZ/../../../bin/run-with-stdout-logged.py}"
DST="$DMZ/.docker-import/run-with-stdout-logged.py"

mkdir -p "$DMZ/.docker-import"
if [ ! -f "$SRC" ]; then
	echo "dmz: missing log wrapper: $SRC" >&2
	echo "  Expected ../../../bin/run-with-stdout-logged.py (bin repo next to utils/), or set DMZ_RUN_WITH_SRC." >&2
	exit 1
fi
cp "$SRC" "$DST"
