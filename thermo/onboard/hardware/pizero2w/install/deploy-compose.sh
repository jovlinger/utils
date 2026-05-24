#!/bin/sh
# Pull images and start/stop the thermo-onboard stack (docker compose).
# Run from install/: ./deploy-compose.sh
# Sources thermo env via THERMO_ENV_FILE (see thermo/config/README.md), then ~/.local.sh.
set -e

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$INSTALL_DIR"
export COMPOSE_PROJECT_NAME="${COMPOSE_PROJECT_NAME:-thermo-onboard}"

log() { echo "[deploy-compose] $*"; }

THERMO_ROOT="$(cd "$INSTALL_DIR/../../../.." && pwd)"
export THERMO_ROOT
export THERMO_ENV_FILE="${THERMO_ENV_FILE:?thermo: set THERMO_ENV_FILE e.g. export THERMO_ENV_FILE=config/kitchen.env}"
set -a
# shellcheck source=/dev/null
. "$THERMO_ROOT/config/source-thermo-env.sh"
set +a

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
	log "Created empty .env - copy env.example to .env or set overrides in ~/.local.sh (DMZ_* comes from THERMO_ENV_FILE)"
fi

if [ -n "${CR_PAT:-}" ]; then
	echo "$CR_PAT" | docker login ghcr.io -u jovlinger --password-stdin 2>/dev/null || true
fi

# ZONE_KEYS_DIR (default thermo/priv/zone) is bind-mounted into twoway as the source for
# /etc/thermo/priv.pem (see docker-compose.yml twoway.volumes). We check & warn here;
# we deliberately do NOT sudo from a deploy script - elevation is a one-time operator step:
#
#   mkdir -p "$THERMO_ROOT/priv/zone"
#   install -m 0400 /path/to/priv.pem "$THERMO_ROOT/priv/zone/priv.pem"
#
# If the dir is absent, Docker will auto-create it as a root-owned empty dir on first
# `compose up`; the container starts with auth DISABLED (twoway logs a loud WARNING) and
# you can install the key later without restarting the host. Override the host dir via
# ZONE_KEYS_DIR (in THERMO_ENV_FILE / ~/.local.sh).
ZONE_KEYS_DIR="${ZONE_KEYS_DIR:-$THERMO_ROOT/priv/zone}"
export ZONE_KEYS_DIR
if [ ! -d "$ZONE_KEYS_DIR" ]; then
	log "WARN: ZONE_KEYS_DIR=$ZONE_KEYS_DIR is missing; docker will auto-create on compose up."
	log "      To enable zone auth: mkdir -p $ZONE_KEYS_DIR &&"
	log "      install -m 0400 /path/to/priv.pem $ZONE_KEYS_DIR/priv.pem"
elif [ ! -f "$ZONE_KEYS_DIR/priv.pem" ]; then
	log "NOTE: $ZONE_KEYS_DIR/priv.pem missing - twoway will start with auth DISABLED."
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
