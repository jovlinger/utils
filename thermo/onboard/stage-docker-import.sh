#!/bin/sh
# Copy run-with-stdout-logged.py from the bin repo (sibling of utils/) into git-ignored
# .docker-import/ for the Docker build context.
# Override: DMZ_RUN_WITH_SRC=/absolute/path/to/run-with-stdout-logged.py
set -eu

ONBOARD="$(cd "$(dirname "$0")" && pwd)"
SRC="${DMZ_RUN_WITH_SRC:-$ONBOARD/../../../bin/run-with-stdout-logged.py}"
DST="$ONBOARD/.docker-import/run-with-stdout-logged.py"

mkdir -p "$ONBOARD/.docker-import"
if [ ! -f "$SRC" ]; then
	echo "onboard: missing log wrapper: $SRC" >&2
	echo "  Expected ../../../bin/run-with-stdout-logged.py (bin repo next to utils/), or set DMZ_RUN_WITH_SRC." >&2
	exit 1
fi
cp "$SRC" "$DST"
