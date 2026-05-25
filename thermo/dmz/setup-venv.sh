#!/bin/sh
# Create or sync the thermo/dmz venv used by the manage launcher.
set -eu

SELF="$0"
case "$SELF" in
  */*) ;;
  *) SELF="$(command -v "$SELF")" ;;
esac

DMZ_DIR="$(cd "$(dirname "$SELF")" && pwd)"
UTILS_ROOT="$(cd "$DMZ_DIR/../.." && pwd)"

exec "$UTILS_ROOT/create_pipenv.sh" "$@" thermo/dmz
