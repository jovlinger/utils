#!/bin/sh
# Pull images and start/stop the thermo-onboard stack (docker compose).
# Run from install/: ./deploy-compose.sh
# Sources thermo env via THERMO_ENV_FILE (see thermo/config/README.md), then ~/.local.sh.
set -e

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$INSTALL_DIR"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-thermo-onboard}"

log() { echo "[deploy-compose] $*"; }

THERMO_ROOT="$(cd "$INSTALL_DIR/../.." && pwd)"
export THERMO_ROOT
export THERMO_ENV_FILE="${THERMO_ENV_FILE:?thermo: set THERMO_ENV_FILE e.g. export THERMO_ENV_FILE=config/kitchen.env}"
# shellcheck source=/dev/null
. "$THERMO_ROOT/config/source-thermo-env.sh"

if [ -f "$HOME/.local.sh" ]; then
	# shellcheck source=/dev/null
	. "$HOME/.local.sh"
fi

if [ -z "${DMZ_URL:-}" ] && [ -n "${DMZ_HOST:-}" ]; then
	: "${DMZ_SCHEME:=http}"
	: "${DMZ_PORT:=5000}"
	export DMZ_URL="${DMZ_SCHEME}://${DMZ_HOST}:${DMZ_PORT}"
fi

# Allow variable substitution in docker-compose.yml (optional file)
if [ ! -f .env ]; then
	touch .env
	log "Created empty .env — copy env.example to .env or set overrides in ~/.local.sh (DMZ_* comes from THERMO_ENV_FILE)"
fi

if [ -n "${CR_PAT:-}" ]; then
	echo "$CR_PAT" | docker login ghcr.io -u jovlinger --password-stdin 2>/dev/null || true
fi

CMD="${1:-up}"
case "$CMD" in
up | start)
	docker compose pull
	docker compose up -d
	docker compose ps
	log "Stack is up. Logs: ${THERMO_LOG_DIR:-/var/log/thermo-onboard}"
	;;
down | stop)
	docker compose down
	;;
*)
	log "usage: $0 [up|down]" >&2
	exit 1
	;;
esac
