#!/bin/bash
# Rebuild image, run the same container shape as `make runlocal` (default entrypoint,
# port 8080), wait for HTTP, then pytest test_smoke.py against the live server from
# the repo venv (../env).
#
# Usage:
#   ./smoketest/run.sh
#   ./smoketest/run.sh --no-cache   # docker build --no-cache
#
# Requires: docker, curl, venv at ../env (see test/run.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DMZ="$(cd "$SCRIPT_DIR/.." && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

if [ ! -f "$DMZ/env/bin/activate" ]; then
	echo "No venv at $DMZ/env." >&2
	echo "Run: $UTILS_ROOT/create_pipenv.sh thermo/dmz" >&2
	exit 1
fi

if ! command -v docker >/dev/null 2>&1; then
	echo "docker not found." >&2
	exit 1
fi

CONTAINER_NAME="dmz-smoketest"
IMAGE="jovlinger/thermo/dmz"
DMZ_URL="${DMZ_URL:-http://127.0.0.1:8080}"

cd "$DMZ"
# shellcheck source=/dev/null
. "$DMZ/env/bin/activate"

cleanup() {
	docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "==> stage .docker-import (../../../bin/run-with-stdout-logged.py)"
"$DMZ/stage-docker-import.sh"

if [ "${1:-}" = "--no-cache" ]; then
	echo "==> docker build --no-cache (fresh image)"
	docker build --no-cache -q -t "$IMAGE" "$DMZ"
else
	echo "==> docker build (fresh image)"
	docker build -q -t "$IMAGE" "$DMZ"
fi

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

echo "==> docker run (same as make runlocal: -p 8080:8080, default entrypoint), detached"
docker run -d --rm -p 8080:8080 --name "$CONTAINER_NAME" "$IMAGE"

echo "==> wait for HTTP (GET /zones, up to 120s; container runs pytest+probes before app)"
ready=0
for _ in $(seq 1 120); do
	if curl -sf --max-time 2 "${DMZ_URL}/zones" >/dev/null 2>&1; then
		ready=1
		break
	fi
	sleep 1
done
if [ "$ready" -ne 1 ]; then
	echo "Error: DMZ did not become ready at ${DMZ_URL}" >&2
	docker logs "$CONTAINER_NAME" >&2 || true
	exit 1
fi

echo "==> pytest smoketest (DMZ_URL=$DMZ_URL)"
export DMZ_URL
pytest -q "$SCRIPT_DIR/test_smoke.py"

echo "==> ok"
