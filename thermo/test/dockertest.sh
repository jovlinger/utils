#!/bin/bash

# This is the command-line test driver.
# This composes a docker container and runs it. This is run OUTSIDE the container
#
# Progress (timestamps + docker stdout) is copied to .dockertest-last.log so you can
# see the last completed step after a hang or external kill:  tail -50 .dockertest-last.log

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
THERMO="$(cd "$SCRIPT_DIR/.." && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
LOG="$SCRIPT_DIR/.dockertest-last.log"

# When invoked via `make dockertest`, PLATFORM is set in the Makefile. For direct
# `./dockertest.sh` after manual builds, export PLATFORM yourself if needed.
export DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-1}"

dockertest_log() {
	local msg="dockertest $(date -u '+%Y-%m-%dT%H:%M:%SZ') $*"
	printf '%s\n' "$msg" | tee -a "$LOG"
}

: >"$LOG"
dockertest_log "start pid=$$ pwd=$PWD PLATFORM=${PLATFORM:-<unset>} DOCKER_BUILDKIT=$DOCKER_BUILDKIT"

# gen_keys.py needs zone_auth (thermo/dmz) or thermo/test deps
if [ ! -f "$THERMO/test/env/bin/activate" ] && [ ! -f "$THERMO/dmz/env/bin/activate" ]; then
	echo "No venv at thermo/test/env or thermo/dmz/env." >&2
	echo "Run: $UTILS_ROOT/create_pipenv.sh thermo/test thermo/dmz" >&2
	exit 1
fi

# Generate Ed25519 keys for machine auth (twoway -> dmz)
mkdir -p keys
dockertest_log "gen_keys: begin"
if [ -f "$THERMO/test/env/bin/python" ]; then
	"$THERMO/test/env/bin/python" gen_keys.py 2>/dev/null || true
elif [ -f "$THERMO/dmz/env/bin/python" ]; then
	"$THERMO/dmz/env/bin/python" gen_keys.py 2>/dev/null || true
fi
dockertest_log "gen_keys: done"

dockertest_log "docker compose up --build --exit-code-from testdriver (streaming to log + stdout)"
# | cat: non-tty so compose/build skip spinner redraws. tee: keeps a transcript if the runner is killed mid-build.
if ! docker compose up --timestamps --abort-on-container-exit --always-recreate-deps --build --exit-code-from testdriver 2>&1 | tee -a "$LOG" | cat; then
	ec="${PIPESTATUS[0]}"
	dockertest_log "docker compose failed (PIPESTATUS[0]=$ec)"
	exit "$ec"
fi
dockertest_log "docker compose ok"
