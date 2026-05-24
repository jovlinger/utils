#!/bin/bash
# Host venv, pytest against source (Flask test_client + layout): no running container.
# CI / parity with image: `make test-docker` from thermo/dmz (pytest in Docker).
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DMZ="$(cd "$SCRIPT_DIR/.." && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# shellcheck source=/dev/null
. "$UTILS_ROOT/venv-resolve.sh"
resolve_utils_venv "$DMZ" "$UTILS_ROOT"

cd "$DMZ"
# shellcheck source=/dev/null
. "$VENV_DIR/bin/activate"
# -v: one line per test case (node id), not only per file (-q).
# --maxfail=3: stop after three failures (systemic bug); override: ./test/run.sh --maxfail=0
pytest -v -ra --maxfail=3 "$@"
