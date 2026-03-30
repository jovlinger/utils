#!/bin/sh
# Twoway sync container: one process, log wrapper only (no Docker log growth).
set -eu

ONBOARD_URL="${ONBOARD_URL:-http://127.0.0.1:5000}"
DMZ_URL="${DMZ_URL:-http://dmz:5000}"
ZONE="${ZONE_NAME:-zoneymczoneface}"
LOG_DIR="${LOG_DIR:-/var/log/thermo-onboard}"
LOG_PATH="${LOG_PATH:-$LOG_DIR/twoway.log}"
LOG_FILELIMIT="${LOG_FILELIMIT:-1048576}"
LOG_TOTALLIMIT="${LOG_TOTALLIMIT:-2097152}"

READ="${ONBOARD_URL%/}/environment"
DMZ_SENSORS="${DMZ_URL%/}/zone/${ZONE}/sensors"
WRITE="${ONBOARD_URL%/}/daikin"

mkdir -p "$(dirname "$LOG_PATH")"

export LOG_PATH

exec python ./bin/run-with-stdout-logged.py "$LOG_PATH" "$LOG_FILELIMIT" "$LOG_TOTALLIMIT" \
  python twoway.py "$READ" "$DMZ_SENSORS" "$WRITE"
