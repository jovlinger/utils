#!/bin/bash
# Rebuild image, run the same container shape as `make runlocal` (default entrypoint,
# port 8080), wait for HTTP, then pytest test_smoke.py against the live server from
# the repo venv (../env).
#
# Usage:
#   ./smoketest/run.sh
#   ./smoketest/run.sh --no-cache
#   ./smoketest/run.sh --leave-container
#   ./smoketest/run.sh --no-cache --leave-container
#
# Requires: docker, curl, venv at ../env (see test/run.sh).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DMZ="$(cd "$SCRIPT_DIR/.." && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

NO_CACHE=0
LEAVE_CONTAINER=0
for arg in "$@"; do
	case "$arg" in
	--no-cache) NO_CACHE=1 ;;
	--leave-container) LEAVE_CONTAINER=1 ;;
	*)
		echo "Unknown option: $arg" >&2
		echo "Usage: $0 [--no-cache] [--leave-container]" >&2
		exit 1
		;;
	esac
done

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
DMZ_LOG_IN_CONTAINER="/var/log/dmz.log"

cd "$DMZ"
# shellcheck source=/dev/null
. "$DMZ/env/bin/activate"

dump_container_app_log_tail() {
	local n="${1:-60}"
	if ! docker inspect "$CONTAINER_NAME" >/dev/null 2>&1; then
		return 0
	fi
	echo "==> app log inside container ($DMZ_LOG_IN_CONTAINER, last $n lines)"
	docker exec "$CONTAINER_NAME" tail -n "$n" "$DMZ_LOG_IN_CONTAINER" 2>/dev/null \
		|| echo "    (tail failed or file missing)"
}

cleanup() {
	if [ "$LEAVE_CONTAINER" -eq 1 ]; then
		echo "==> leaving container $CONTAINER_NAME running (--leave-container)"
		echo "    e.g. docker logs -f $CONTAINER_NAME"
		echo "    or: docker exec -it $CONTAINER_NAME tail -f $DMZ_LOG_IN_CONTAINER"
		return 0
	fi
	docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

echo "==> stage .docker-import (bin/run-with-stdout-logged.py)"
"$DMZ/stage-docker-import.sh"

if [ "$NO_CACHE" -eq 1 ]; then
	echo "==> docker build --no-cache (fresh image)"
	docker build --no-cache -q -t "$IMAGE" "$DMZ"
else
	echo "==> docker build (fresh image)"
	docker build -q -t "$IMAGE" "$DMZ"
fi

docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

echo "==> docker run (same as make runlocal: -p 8080:8080, default entrypoint), detached"
if [ "$LEAVE_CONTAINER" -eq 1 ]; then
	# No --rm so the container stays after this script exits (still running).
	docker run -d -p 8080:8080 --name "$CONTAINER_NAME" "$IMAGE"
else
	docker run -d --rm -p 8080:8080 --name "$CONTAINER_NAME" "$IMAGE"
fi

echo "==> wait for HTTP (GET /zones, up to 120s; container runs unittest+probes before app)"
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
	dump_container_app_log_tail 120 >&2 || true
	exit 1
fi

echo "==> pytest smoketest (DMZ_URL=$DMZ_URL)"
export DMZ_URL
cd "$SCRIPT_DIR"
# -v names tests; -s disables capture; ./pytest.ini enables log_cli for logger lines.
pytest -v -s test_smoke.py

dump_container_app_log_tail 80

echo "==> ok"
