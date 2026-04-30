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

ensure_tmpfs_log_symlink() {
	LOG_LINK="/var/log/thermo-onboard"
	LOG_TMPFS_DIR="/run/thermo-onboard-log"
	OLD_DIR_BACKUP="/var/log/thermo-onboard.pre-tmpfs"
	AS_ROOT=""
	if [ "$(id -u)" -ne 0 ]; then
		AS_ROOT="sudo"
	fi

	$AS_ROOT mkdir -p "$LOG_TMPFS_DIR"
	$AS_ROOT chmod 0755 "$LOG_TMPFS_DIR"

	if [ -L "$LOG_LINK" ]; then
		_target="$(readlink "$LOG_LINK" 2>/dev/null || true)"
		if [ "$_target" = "$LOG_TMPFS_DIR" ]; then
			log "tmpfs log symlink already set: $LOG_LINK -> $_target"
			return 0
		fi
	fi

	if [ -d "$LOG_LINK" ] && [ ! -L "$LOG_LINK" ]; then
		$AS_ROOT rm -rf "$OLD_DIR_BACKUP"
		$AS_ROOT mv "$LOG_LINK" "$OLD_DIR_BACKUP"
		log "moved existing log dir to $OLD_DIR_BACKUP"
	fi

	$AS_ROOT rm -rf "$LOG_LINK"
	$AS_ROOT ln -s "$LOG_TMPFS_DIR" "$LOG_LINK"
	log "set tmpfs log symlink: $LOG_LINK -> $LOG_TMPFS_DIR"
}

if [ -n "$PI_HOST" ]; then
	: "${THERMO_ENV_FILE:?set THERMO_ENV_FILE e.g. export THERMO_ENV_FILE=config/kitchen.env (path relative to thermo/ on the Pi)}"
	log "Deploy from dev machine -> $PI_HOST (git pull + deploy-compose on Pi) THERMO_ENV_FILE=$THERMO_ENV_FILE"
	ssh "johan@$PI_HOST" "cd ~/github.com/jovlinger/utils && export THERMO_ENV_FILE=\"$THERMO_ENV_FILE\" && chmod +x thermo/onboard/install/deploy.sh && thermo/onboard/install/deploy.sh"
	log "Deploy complete."
	exit 0
fi

if [ ! -d "$REPO" ]; then
	log "Repo not found: $REPO. Set REPO_PATH or run: ./deploy.sh pizero.local"
	exit 1
fi

: "${THERMO_ENV_FILE:?set THERMO_ENV_FILE e.g. export THERMO_ENV_FILE=config/kitchen.env}"
log "Deploy on Pi: $REPO THERMO_ENV_FILE=$THERMO_ENV_FILE"
cd "$REPO"
git pull
ensure_tmpfs_log_symlink
cd thermo/onboard/install
chmod +x deploy-compose.sh
./deploy-compose.sh
log "Deploy complete."
