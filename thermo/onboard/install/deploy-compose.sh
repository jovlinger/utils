#!/bin/sh
# Pull images and start/stop the thermo-onboard stack (docker compose).
# Run from install/: ./deploy-compose.sh
# Sources ~/.local.sh when present (CR_PAT, DMZ_URL, etc.).
set -e

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$INSTALL_DIR"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-thermo-onboard}"

log() { echo "[deploy-compose] $*"; }

if [ -f "$HOME/.local.sh" ]; then
	# shellcheck source=/dev/null
	. "$HOME/.local.sh"
fi

# Allow variable substitution in docker-compose.yml (optional file)
if [ ! -f .env ]; then
	touch .env
	log "Created empty .env — copy env.example to .env or set DMZ_URL in ~/.local.sh"
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
