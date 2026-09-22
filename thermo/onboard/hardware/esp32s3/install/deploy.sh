#!/bin/sh
# Deploy MicroPython debug app to ESP32-S3 via mpremote (no Jaguar/Toit).
# Uploads only files listed in upload.manifest (omits ir_midea / ir_daikin).
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ESP32_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MP_DIR="$ESP32_DIR/mp"
MANIFEST="$SCRIPT_DIR/upload.manifest"
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
	log "preflight ok (mpremote upload; flash MicroPython separately if needed)"
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

PORT="${ESP32S3_FLASH_PORT:-${MPREMOTE_PORT:-}}"
if [ -z "$PORT" ]; then
	log "set ESP32S3_FLASH_PORT (or MPREMOTE_PORT) to the USB serial device"
	exit 1
fi

MPREMOTE="${THERMO_ROOT}/onboard/.venv/bin/mpremote"
if [ ! -x "$MPREMOTE" ]; then
	if command -v mpremote >/dev/null 2>&1; then
		MPREMOTE=mpremote
	else
		log "mpremote not found; pip install mpremote in thermo/onboard/.venv"
		exit 1
	fi
fi

if [ ! -f "$MANIFEST" ]; then
	log "missing $MANIFEST"
	exit 1
fi

log "uploading from $MP_DIR via $MPREMOTE connect $PORT"
cd "$MP_DIR"
files=""
while IFS= read -r rel || [ -n "$rel" ]; do
	case "$rel" in
	"" | \#*) continue ;;
	esac
	if [ ! -f "$MP_DIR/$rel" ]; then
		log "manifest entry missing: $rel"
		exit 1
	fi
	case "$rel" in
	ir_daikin.py)
		log "refusing to upload IR dialect $rel (omit policy)"
		exit 1
		;;
	esac
	files="$files $rel"
done <"$MANIFEST"
# shellcheck disable=SC2086
"$MPREMOTE" connect "$PORT" cp $files :
log "uploaded manifest files (IR dialects omitted)"
log "done"
