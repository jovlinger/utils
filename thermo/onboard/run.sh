# common entry point, invoked by container, per Dockerfile
# Logs go to LOG_PATH (default /tmp/onboard.log) via run-with-stdout-logged.py.
# When run locally, asserts pip env exists.

# Use 127.0.0.1 for onboard (host network has no Docker DNS). Override DMZ_URL or DMZ_HOST in the environment;
# Optional: export THERMO_ENV_FILE=config/kitchen.env and THERMO_ROOT is set below.
_SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
THERMO_ROOT="$(cd "$_SCRIPT_DIR/.." && pwd)"
export THERMO_ROOT
if [ -n "${THERMO_ENV_FILE:-}" ]; then
	# shellcheck source=/dev/null
	. "$THERMO_ROOT/config/source-thermo-env.sh"
fi
: "${DMZ_SCHEME:=http}"
: "${DMZ_HOST:=jovlinger.duckdns.org}"
: "${DMZ_PORT:=5000}"
if [ -z "${DMZ_URL:-}" ]; then
	export DMZ_URL="${DMZ_SCHEME}://${DMZ_HOST}:${DMZ_PORT}"
fi
ONBOARD="${ONBOARD_URL:-http://127.0.0.1:5000}"
DMZ="${DMZ_URL}"
ZONE="${ZONE_NAME:-kitchen}"
LOG_PATH="${LOG_PATH:-/tmp/onboard.log}"
LOG_FILELIMIT="${LOG_FILELIMIT:-1048576}"
LOG_TOTALLIMIT="${LOG_TOTALLIMIT:-2097152}"
export LOG_PATH

if [ -f /.dockerenv ]; then
  # Production uses docker-compose: onboard-app + twoway containers
  # (see hardware/pizero2w/install/docker-compose.yml).
  # Legacy single image: use docker-entrypoint-onboard.sh / Dockerfile.onboard only.
  exec ./docker-entrypoint-onboard.sh
fi

SCRIPT_DIR="$_SCRIPT_DIR"
# utils repo root (for venv path hints).
COMMON_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
RUN_WITH_STDOUT="$(cd "$SCRIPT_DIR/../../extdeps" && pwd)/run-with-stdout-logged.py"
if [ ! -f "$SCRIPT_DIR/env/bin/activate" ]; then
  echo "No venv at $SCRIPT_DIR/env." >&2
  echo "Run: $COMMON_ROOT/create_pipenv.sh thermo/onboard" >&2
  exit 1
fi
. "$SCRIPT_DIR/env/bin/activate"
python twoway.py "${ONBOARD}/environment" "${DMZ}/zone/${ZONE}/sensors" "${ONBOARD}/daikin" &
export PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
if [ "${THERMO_UI_DISABLE:-0}" != "1" ]; then
	python "$SCRIPT_DIR/../ui/ui_server.py" &
fi
echo "starting app"
exec python "$RUN_WITH_STDOUT" "$LOG_PATH" "$LOG_FILELIMIT" "$LOG_TOTALLIMIT" python app.py
