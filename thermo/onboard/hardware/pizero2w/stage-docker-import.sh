#!/bin/sh
# Copy run-with-stdout-logged.py from repo-root extdeps/ (snapshots; see extdeps/Makefile).
# into git-ignored .docker-import/ for the Docker build context.
# Override: DMZ_RUN_WITH_SRC=/absolute/path/to/run-with-stdout-logged.py
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONBOARD="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENDORED="$ONBOARD/../../extdeps/run-with-stdout-logged.py"
SRC="${DMZ_RUN_WITH_SRC:-$VENDORED}"
DST="$ONBOARD/.docker-import/run-with-stdout-logged.py"

mkdir -p "$ONBOARD/.docker-import"
if [ ! -f "$SRC" ]; then
	echo "onboard: missing log wrapper: $SRC" >&2
	echo "  Expected $VENDORED, or set DMZ_RUN_WITH_SRC." >&2
	exit 1
fi
cp "$SRC" "$DST"

UI_SRC="$ONBOARD/../ui"
UI_DST="$ONBOARD/.docker-import/ui"
if [ ! -d "$UI_SRC" ]; then
	echo "onboard: missing shared UI dir: $UI_SRC" >&2
	exit 1
fi
rm -rf "$UI_DST"
mkdir -p "$UI_DST"
cp -R "$UI_SRC"/. "$UI_DST/"
