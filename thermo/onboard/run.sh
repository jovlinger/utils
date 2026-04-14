# common entry point, invoked by container, per Dockerfile
# Logs go to LOG_PATH (default /tmp/onboard.log) via run-with-stdout-logged.py.
# When run locally, asserts pip env exists.

# this hardcodes "this" onboard zone's name as zoneymczoneface
# Use 127.0.0.1 for onboard (host network has no Docker DNS). Override ONBOARD_URL/DMZ_URL for docker-compose.
ONBOARD="${ONBOARD_URL:-http://127.0.0.1:5000}"
DMZ="${DMZ_URL:-http://dmz:5000}"
LOG_PATH="${LOG_PATH:-/tmp/onboard.log}"
LOG_FILELIMIT="${LOG_FILELIMIT:-1048576}"
LOG_TOTALLIMIT="${LOG_TOTALLIMIT:-2097152}"
export LOG_PATH

if [ -f /.dockerenv ]; then
  # Production uses docker-compose: onboard-app + twoway containers (see install/docker-compose.yml).
  # Legacy single image: use docker-entrypoint-onboard.sh / Dockerfile.onboard only.
  exec ./docker-entrypoint-onboard.sh
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# utils repo root (for venv path hints).
COMMON_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUN_WITH_STDOUT="$(cd "$SCRIPT_DIR/../../bin" && pwd)/run-with-stdout-logged.py"
if [ ! -f "$SCRIPT_DIR/env/bin/activate" ]; then
  echo "No venv at $SCRIPT_DIR/env." >&2
  echo "Run: $COMMON_ROOT/create_pipenv.sh thermo/onboard" >&2
  exit 1
fi
. "$SCRIPT_DIR/env/bin/activate"
python twoway.py "${ONBOARD}/environment" "${DMZ}/zone/zoneymczoneface/sensors" "${ONBOARD}/daikin" &
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
python "$SCRIPT_DIR/../ui/ui_server.py" &
echo "starting app"
exec python "$RUN_WITH_STDOUT" "$LOG_PATH" "$LOG_FILELIMIT" "$LOG_TOTALLIMIT" python app.py
