# common entry point, invoked by container, per Dockerfile
# Logs go to LOG_PATH (default /tmp/onboard.log), pruned by LOG_MAX_LINES.
# When run locally, asserts pip env exists.

# this hardcodes "this" onboard zone's name as zoneymczoneface
# Use 127.0.0.1 for onboard (host network has no Docker DNS). Override ONBOARD_URL/DMZ_URL for docker-compose.
ONBOARD="${ONBOARD_URL:-http://127.0.0.1:5000}"
DMZ="${DMZ_URL:-http://dmz:5000}"

if [ -f /.dockerenv ]; then
  python twoway.py "${ONBOARD}/environment" "${DMZ}/zone/zoneymczoneface/sensors" "${ONBOARD}/daikin" &
  python ui_server.py &
  echo "starting app"
  exec python app.py
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
if [ ! -f "$SCRIPT_DIR/env/bin/activate" ]; then
  echo "No venv at $SCRIPT_DIR/env." >&2
  echo "Run: $UTILS_ROOT/create_pipenv.sh thermo/onboard" >&2
  exit 1
fi
. "$SCRIPT_DIR/env/bin/activate"
python twoway.py "${ONBOARD}/environment" "${DMZ}/zone/zoneymczoneface/sensors" "${ONBOARD}/daikin" &
python ui_server.py &
echo "starting app"
exec python app.py
