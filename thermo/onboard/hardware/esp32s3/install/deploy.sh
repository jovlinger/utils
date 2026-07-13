#!/bin/sh
# Deploy the office ESP32-S3 thermo container over Jaguar WiFi (borgify).
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ESP32_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO="${REPO_PATH:-$(cd "$ESP32_DIR/../../../.." && pwd)}"
THERMO_ROOT="$REPO/thermo"
export THERMO_ROOT

log() { echo "[esp32s3-deploy] $*"; }

if [ ! -d "$REPO" ]; then
	log "Repo not found: $REPO. Set REPO_PATH."
	exit 1
fi

: "${THERMO_ENV_FILE:?set THERMO_ENV_FILE e.g. onboard/zones/office/zone.env}"

if [ "${1:-}" = "--preflight" ]; then
	log "preflight ok (Jaguar WiFi deploy; no serial flash in preflight)"
	exit 0
fi

if [ -f "$THERMO_ROOT/config/source-thermo-env.sh" ]; then
	set -a
	# shellcheck source=/dev/null
	. "$THERMO_ROOT/config/source-thermo-env.sh"
	set +a
fi

: "${ONBOARD_DEPLOY_BACKEND:?set ONBOARD_DEPLOY_BACKEND=esp32s3 in $THERMO_ENV_FILE}"
if [ "$ONBOARD_DEPLOY_BACKEND" != "esp32s3" ]; then
	echo "ONBOARD_DEPLOY_BACKEND=$ONBOARD_DEPLOY_BACKEND does not match esp32s3" >&2
	exit 1
fi

ESP32S3_PRIV_ENV="${ESP32S3_PRIV_ENV:-$THERMO_ROOT/priv/esp32s3/${ZONE_NAME:-office}.env}"
if [ -f "$ESP32S3_PRIV_ENV" ]; then
	set -a
	# shellcheck source=/dev/null
	. "$ESP32S3_PRIV_ENV"
	set +a
	log "loaded private ESP32-S3 env: $ESP32S3_PRIV_ENV"
fi

ESP32S3_JAGUAR_DEVICE_NAME="${ESP32S3_JAGUAR_DEVICE_NAME:-esp32s3-office}"
ESP32S3_JAGUAR_CONTAINER_NAME="${ESP32S3_JAGUAR_CONTAINER_NAME:-thermo-esp32s3}"
ESP32S3_JAGUAR_DEVICE="${ESP32S3_JAGUAR_DEVICE:-${ESP32S3_JAGUAR_DEVICE_ADDRESS:-$ESP32S3_JAGUAR_DEVICE_NAME}}"

if ! command -v jag >/dev/null 2>&1; then
	log "jag not found; install with: brew install jaguar && jag setup"
	exit 1
fi

cd "$ESP32_DIR"

log "selecting Jaguar device: $ESP32S3_JAGUAR_DEVICE"
if ! jag scan "$ESP32S3_JAGUAR_DEVICE" >/dev/null 2>&1; then
	log "device not found at $ESP32S3_JAGUAR_DEVICE; trying jag scan -l"
	ESP32S3_JAGUAR_DEVICE="$(jag scan -l 2>/dev/null | head -1 || true)"
	if [ -z "$ESP32S3_JAGUAR_DEVICE" ]; then
		log "no Jaguar device found on LAN"
		exit 1
	fi
	log "using first discovered device name: $ESP32S3_JAGUAR_DEVICE"
	jag scan "$ESP32S3_JAGUAR_DEVICE" >/dev/null
fi

current_name="$(jag scan -l 2>/dev/null | head -1 || true)"
if [ -n "$current_name" ] && [ "$current_name" != "$ESP32S3_JAGUAR_DEVICE_NAME" ]; then
	log "renaming device $current_name -> $ESP32S3_JAGUAR_DEVICE_NAME (OTA)"
	jag firmware update --name "$ESP32S3_JAGUAR_DEVICE_NAME" -d "$ESP32S3_JAGUAR_DEVICE"
	jag scan "$ESP32S3_JAGUAR_DEVICE_NAME" >/dev/null
	ESP32S3_JAGUAR_DEVICE="$ESP32S3_JAGUAR_DEVICE_NAME"
fi

log "borgifying container $ESP32S3_JAGUAR_CONTAINER_NAME from src/main.toit"
jag container install "$ESP32S3_JAGUAR_CONTAINER_NAME" src/main.toit -d "$ESP32S3_JAGUAR_DEVICE"

log "installed containers:"
jag container list -d "$ESP32S3_JAGUAR_DEVICE"
log "done"
