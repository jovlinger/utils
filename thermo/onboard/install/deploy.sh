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
set -a
# shellcheck source=/dev/null
. "$THERMO_ROOT/config/source-thermo-env.sh"
set +a

ONBOARD_DEPLOY_BACKEND="${ONBOARD_DEPLOY_BACKEND:-pizero2w}"
export ONBOARD_DEPLOY_BACKEND

BACKEND_DEPLOY="$REPO/thermo/onboard/hardware/$ONBOARD_DEPLOY_BACKEND/install/deploy.sh"
if [ ! -f "$BACKEND_DEPLOY" ]; then
	log "No deploy backend for ONBOARD_DEPLOY_BACKEND=$ONBOARD_DEPLOY_BACKEND: $BACKEND_DEPLOY"
	exit 1
fi

log "Deploy backend=$ONBOARD_DEPLOY_BACKEND THERMO_ENV_FILE=$THERMO_ENV_FILE"
REPO_PATH="$REPO" /bin/sh "$BACKEND_DEPLOY" "$@"
