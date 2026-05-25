#!/bin/sh
# Copy run-with-stdout-logged.py from repo-root extdeps/ (snapshots; see extdeps/Makefile).
# into git-ignored .docker-import/ so the DMZ Dockerfile can COPY it (build context is thermo/dmz only).
# Override: DMZ_RUN_WITH_SRC=/absolute/path/to/run-with-stdout-logged.py
set -eu

DMZ="$(cd "$(dirname "$0")" && pwd)"
VENDORED="$DMZ/../../extdeps/run-with-stdout-logged.py"
SRC="${DMZ_RUN_WITH_SRC:-$VENDORED}"
DST="$DMZ/.docker-import/run-with-stdout-logged.py"

mkdir -p "$DMZ/.docker-import"
if [ ! -f "$SRC" ]; then
	echo "dmz: missing log wrapper: $SRC" >&2
	echo "  Expected $VENDORED, or set DMZ_RUN_WITH_SRC." >&2
	exit 1
fi
cp "$SRC" "$DST"

HP_SRC="$DMZ/../onboard/heatpumpirctl"
HP_DST="$DMZ/.docker-import/heatpumpirctl"
if [ ! -d "$HP_SRC" ]; then
	echo "dmz: missing heatpumpirctl: $HP_SRC" >&2
	exit 1
fi
rm -rf "$HP_DST"
mkdir -p "$HP_DST"
cp -R "$HP_SRC"/. "$HP_DST/"

UI_SRC="$DMZ/../ui"
UI_DST="$DMZ/.docker-import/ui"
if [ ! -d "$UI_SRC" ]; then
	echo "dmz: missing shared UI dir: $UI_SRC" >&2
	exit 1
fi
rm -rf "$UI_DST"
mkdir -p "$UI_DST"
cp -R "$UI_SRC"/. "$UI_DST/"
