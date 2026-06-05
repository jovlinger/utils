#!/bin/sh
# Deploy a Pi Zero 2 W room target, either over SSH or locally on the target.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO_PATH:-$(cd "$SCRIPT_DIR/../../../../.." && pwd)}"
HOST="${1:-${ONBOARD_DEPLOY_HOST:-}}"
USER_NAME="${ONBOARD_DEPLOY_USER:-johan}"
REMOTE_REPO="${ONBOARD_DEPLOY_REPO:-~/github.com/jovlinger/utils}"
REMOTE_ENV_FILE="${ONBOARD_DEPLOY_ENV_FILE:-${THERMO_ENV_FILE:-}}"

log() { echo "[pizero2w-deploy] $*"; }

is_local_host() {
	_host="$1"
	[ -n "$_host" ] || return 1
	_host_short="${_host%%.*}"
	_this="$(hostname 2>/dev/null || true)"
	_this_short="${_this%%.*}"
	_this_fqdn="$(hostname -f 2>/dev/null || true)"
	[ "$_host" = "$_this" ] && return 0
	[ "$_host" = "$_this_fqdn" ] && return 0
	[ "$_host_short" = "$_this_short" ] && return 0
	return 1
}

if [ -n "$HOST" ] && [ "${ONBOARD_DEPLOY_LOCAL:-0}" != "1" ] && ! is_local_host "$HOST"; then
	: "${REMOTE_ENV_FILE:?set ONBOARD_DEPLOY_ENV_FILE or THERMO_ENV_FILE for remote deploy}"
	log "Remote deploy to $USER_NAME@$HOST repo=$REMOTE_REPO env=$REMOTE_ENV_FILE"
	ssh "$USER_NAME@$HOST" \
		"cd $REMOTE_REPO && git pull && export THERMO_ENV_FILE=\"$REMOTE_ENV_FILE\" ONBOARD_DEPLOY_LOCAL=1 ONBOARD_DEPLOY_SKIP_GIT_PULL=1 && make -C thermo/onboard deploy ZONE=kitchen DEPLOY_REPO=\"\$(pwd)\""
	log "Deploy complete."
	exit 0
fi
if [ -n "$HOST" ] && [ "${ONBOARD_DEPLOY_LOCAL:-0}" != "1" ]; then
	log "Host $HOST matches this machine; deploying locally."
fi

if [ ! -d "$REPO" ]; then
	log "Repo not found: $REPO. Set REPO_PATH."
	exit 1
fi

: "${THERMO_ENV_FILE:?set THERMO_ENV_FILE e.g. export THERMO_ENV_FILE=config/kitchen.env}"

# THERMO_DEPLOY_ROOT: optional prefix for tests / hosts without writable /run.
# When set, log paths become $ROOT/run/thermo-onboard-log and symlink
# $ROOT/var/log/thermo-onboard with no sudo.
ensure_tmpfs_log_symlink() {
	LOG_LINK="/var/log/thermo-onboard"
	LOG_TMPFS_DIR="/run/thermo-onboard-log"
	OLD_DIR_BACKUP="/var/log/thermo-onboard.pre-tmpfs"
	AS_ROOT=""
	if [ -n "${THERMO_DEPLOY_ROOT:-}" ]; then
		_root="${THERMO_DEPLOY_ROOT%/}"
		LOG_TMPFS_DIR="$_root/run/thermo-onboard-log"
		LOG_LINK="$_root/var/log/thermo-onboard"
		OLD_DIR_BACKUP="$_root/var/log/thermo-onboard.pre-tmpfs"
	elif [ "$(id -u)" -ne 0 ]; then
		AS_ROOT="sudo"
	fi

	$AS_ROOT mkdir -p "$LOG_TMPFS_DIR"
	$AS_ROOT chmod 0755 "$LOG_TMPFS_DIR"
	$AS_ROOT mkdir -p "$(dirname "$LOG_LINK")"

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

log "Local deploy repo=$REPO env=$THERMO_ENV_FILE"
cd "$REPO"
if [ "${ONBOARD_DEPLOY_SKIP_GIT_PULL:-0}" != "1" ]; then
	git pull
fi
ensure_tmpfs_log_symlink
cd thermo/onboard/hardware/pizero2w/install
/bin/sh ./deploy-compose.sh "$@"
log "Deploy complete."
