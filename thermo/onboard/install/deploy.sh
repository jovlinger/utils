#!/bin/sh
# Deploy thermo-onboard: git pull, then compose pull + up (or dev: build/push + SSH).
#
# On Pi (repo on Pi):
#   cd ~/github.com/jovlinger/utils && git pull && thermo/onboard/install/deploy.sh
#
# From dev machine (SSH to Pi for pull + deploy-compose only):
#   ./deploy.sh pizero.local
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO_PATH:-$HOME/github.com/jovlinger/utils}"
PI_HOST="${1:-}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

if [ -n "$PI_HOST" ]; then
	log "Deploy from dev machine -> $PI_HOST (git pull + deploy-compose on Pi)"
	ssh "johan@$PI_HOST" 'cd ~/github.com/jovlinger/utils && git pull && cd thermo/onboard/install && chmod +x deploy-compose.sh && ./deploy-compose.sh'
	log "Deploy complete."
	exit 0
fi

if [ ! -d "$REPO" ]; then
	log "Repo not found: $REPO. Set REPO_PATH or run: ./deploy.sh pizero.local"
	exit 1
fi

log "Deploy on Pi: $REPO"
cd "$REPO"
git pull
cd thermo/onboard/install
chmod +x deploy-compose.sh
./deploy-compose.sh
log "Deploy complete."
