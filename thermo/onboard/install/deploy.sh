#!/bin/sh
# Deploy thermo-onboard: git pull, build, push, restart container.
# Run on Pi (repo on Pi) or dev machine (then SSHs to Pi for restart).
#
# On Pi: REPO_PATH=~/github.com/jovlinger/utils ./deploy.sh
# From dev: ./deploy.sh [pizero.local]

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO_PATH:-$HOME/github.com/jovlinger/utils}"
PI_HOST="${1:-}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

if [ -n "$PI_HOST" ]; then
    # Dev machine: build and push here, then SSH to Pi for pull+restart
    log "Deploy from dev machine -> $PI_HOST"
    cd "$(cd "$SCRIPT_DIR/../.." && pwd)"
    git pull
    make push
    log "SSH to $PI_HOST for pull and restart..."
    ssh "johan@$PI_HOST" 'cd ~/thermo-onboard-install 2>/dev/null || cd ~/github.com/jovlinger/utils/thermo/onboard/install; ./run-onboard.sh --pull'
    log "Deploy complete."
    exit 0
fi

# Pi: run locally (repo on Pi)
if [ ! -d "$REPO" ]; then
    log "Repo not found: $REPO. Set REPO_PATH or run from dev: ./deploy.sh pizero.local"
    exit 1
fi

log "Deploy on Pi: $REPO"
cd "$REPO"
git pull
cd thermo/onboard
make build
make push
log "Restarting container..."
"$SCRIPT_DIR/run-onboard.sh" --pull
log "Deploy complete."
