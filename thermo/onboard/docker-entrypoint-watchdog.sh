#!/bin/sh
# Connectivity watchdog: logs + incident dumps under LOG_DIR (bind-mounted on the Pi).
set -eu

LOG_DIR="${LOG_DIR:-/var/log/thermo-onboard}"
LOG_PATH="${CONNECTIVITY_LOG_PATH:-$LOG_DIR/connectivity-watchdog.log}"
LOG_FILELIMIT="${CONNECTIVITY_LOG_FILELIMIT:-1048576}"
LOG_TOTALLIMIT="${CONNECTIVITY_LOG_TOTALLIMIT:-2097152}"

mkdir -p "$(dirname "$LOG_PATH")"
mkdir -p "${CONNECTIVITY_DUMP_DIR:-$LOG_DIR/incidents}"

export LOG_PATH
export CONNECTIVITY_LOG_PATH="$LOG_PATH"
export TWOWAY_LOG_PATH="${TWOWAY_LOG_PATH:-$LOG_DIR/twoway.log}"

exec python ./bin/run-with-stdout-logged.py "$LOG_PATH" "$LOG_FILELIMIT" "$LOG_TOTALLIMIT" \
  python connectivity_watchdog.py
