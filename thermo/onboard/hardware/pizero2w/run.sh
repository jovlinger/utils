# common entry point, invoked by container, per Dockerfile
# Logs go to LOG_PATH (default /tmp/onboard.log) via run-with-stdout-logged.py.
# When run locally, asserts pip env exists.

# Use 127.0.0.1 for onboard (host network has no Docker DNS). Override DMZ_URL or DMZ_HOST in the environment;
# Optional: export THERMO_ENV_FILE=config/kitchen.env and THERMO_ROOT is set below.
PIZERO2W_DIR="$(cd "$(dirname "$0")" && pwd)"
ONBOARD_ROOT="$(cd "$PIZERO2W_DIR/../.." && pwd)"
THERMO_ROOT="$(cd "$ONBOARD_ROOT/.." && pwd)"
UTILS_ROOT="$(cd "$THERMO_ROOT/.." && pwd)"
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
  exec "$PIZERO2W_DIR/docker-entrypoint-onboard.sh"
fi

RUN_WITH_STDOUT="$UTILS_ROOT/extdeps/run-with-stdout-logged.py"
if [ ! -f "$ONBOARD_ROOT/env/bin/activate" ]; then
  echo "No venv at $ONBOARD_ROOT/env." >&2
  echo "Run: $UTILS_ROOT/create_pipenv.sh thermo/onboard" >&2
  exit 1
fi
. "$ONBOARD_ROOT/env/bin/activate"
export PYTHONPATH="$ONBOARD_ROOT${PYTHONPATH:+:$PYTHONPATH}"
python -m common.twoway "${ONBOARD}/environment" "${DMZ}/zone/${ZONE}/sensors" "${ONBOARD}/daikin" &
if [ "${THERMO_UI_DISABLE:-0}" != "1" ]; then
	python "$THERMO_ROOT/ui/ui_server.py" &
fi
echo "starting app"
exec python "$RUN_WITH_STDOUT" "$LOG_PATH" "$LOG_FILELIMIT" "$LOG_TOTALLIMIT" \
	python -m hardware.pizero2w.app
