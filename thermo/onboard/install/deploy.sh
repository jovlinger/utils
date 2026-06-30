#!/bin/sh
# Dispatch room deployment to the hardware-specific install backend.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO_PATH:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
THERMO_ROOT="$REPO/thermo"
export THERMO_ROOT

log() { echo "[$(date +%H:%M:%S)] $*"; }

if [ ! -d "$REPO" ]; then
	log "Repo not found: $REPO. Set REPO_PATH."
	exit 1
fi

: "${THERMO_ENV_FILE:?set THERMO_ENV_FILE e.g. export THERMO_ENV_FILE=config/kitchen.env}"
PICO2W_UF2_PATH_OVERRIDE="${PICO2W_UF2_PATH:-}"
PICO2W_UF2_VOLUME_OVERRIDE="${PICO2W_UF2_VOLUME:-}"
set -a
# shellcheck source=/dev/null
. "$THERMO_ROOT/config/source-thermo-env.sh"
set +a
if [ -n "$PICO2W_UF2_PATH_OVERRIDE" ]; then
	PICO2W_UF2_PATH="$PICO2W_UF2_PATH_OVERRIDE"
	export PICO2W_UF2_PATH
fi
if [ -n "$PICO2W_UF2_VOLUME_OVERRIDE" ]; then
	PICO2W_UF2_VOLUME="$PICO2W_UF2_VOLUME_OVERRIDE"
	export PICO2W_UF2_VOLUME
fi

ONBOARD_DEPLOY_BACKEND="${ONBOARD_DEPLOY_BACKEND:-pizero2w}"
export ONBOARD_DEPLOY_BACKEND
if [ -n "${EXPECTED_ONBOARD_DEPLOY_BACKEND:-}" ] && [ "$ONBOARD_DEPLOY_BACKEND" != "$EXPECTED_ONBOARD_DEPLOY_BACKEND" ]; then
	log "Manifest backend=$ONBOARD_DEPLOY_BACKEND does not match expected backend=$EXPECTED_ONBOARD_DEPLOY_BACKEND"
	exit 1
fi

if [ "${1:-}" = "--preflight" ] && [ "$ONBOARD_DEPLOY_BACKEND" != "pico2w" ]; then
	log "No deploy preflight for backend=$ONBOARD_DEPLOY_BACKEND"
	exit 0
fi

BACKEND_DEPLOY="$REPO/thermo/onboard/hardware/$ONBOARD_DEPLOY_BACKEND/install/deploy.sh"
if [ ! -f "$BACKEND_DEPLOY" ]; then
	log "No deploy backend for ONBOARD_DEPLOY_BACKEND=$ONBOARD_DEPLOY_BACKEND: $BACKEND_DEPLOY"
	exit 1
fi

log "Deploy backend=$ONBOARD_DEPLOY_BACKEND THERMO_ENV_FILE=$THERMO_ENV_FILE"
REPO_PATH="$REPO" /bin/sh "$BACKEND_DEPLOY" "$@"
