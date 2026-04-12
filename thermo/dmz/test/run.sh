#!/bin/bash
# Host venv, pytest against source (Flask test_client + layout): no running container.
# CI / parity with image: `make test-docker` from thermo/dmz (pytest in Docker).
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DMZ="$(cd "$SCRIPT_DIR/.." && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

if [ ! -f "$DMZ/env/bin/activate" ]; then
	echo "No venv at $DMZ/env." >&2
	echo "Run: $UTILS_ROOT/create_pipenv.sh thermo/dmz" >&2
	exit 1
fi

cd "$DMZ"
# shellcheck source=/dev/null
. "$DMZ/env/bin/activate"
python -m pytest -q
