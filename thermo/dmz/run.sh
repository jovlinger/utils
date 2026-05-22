# Invoked by start.sh as user `dmz` in the container, or directly with a venv on a dev machine.
# Pi chroot matches the image layout (/app/...) but has no /.dockerenv — same runtime path as Docker.
#
# Startup pytest on test/ is off unless DMZ_RUN_STARTUP_PYTEST=1 (then non-fatal if it fails).
# Then import/smoke probes, then the app.

hostname
whoami

echo "dmz ENV ${ENV:-idk}"

# Probe breadcrumbs (works in Docker and local dev without /var/log).
DMZ_LOG="/tmp/dmz-run.log"

# Log probe step to /tmp/dmz-run.log and stdout (dmz.log via run-with-stdout-logged).
_probe_python_note() {
	line="$(date -u '+%Y-%m-%dT%H:%M:%SZ') $1"
	printf '%s\n' "$line" >>"$DMZ_LOG"
	printf '%s\n' "$line"
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
RUNTIME_IS_CONTAINER=0
APP_ROOT=""
# Host dev machine: repo checkout with create_pipenv venv (not Docker, not Pi).
if [ -f "$SCRIPT_DIR/env/bin/activate" ]; then
	# shellcheck source=/dev/null
	. "$SCRIPT_DIR/env/bin/activate"
	APP_ROOT="$SCRIPT_DIR"
	echo "run.sh: dev uname -m=$(uname -m)"
# Local Docker container (/.dockerenv) or Pi 1B: same image tree under /app after chroot.
elif [ -f /.dockerenv ] || [ -f /app/app.py ]; then
	RUNTIME_IS_CONTAINER=1
	APP_ROOT="/app"
	echo "run.sh: image/chroot uname -m=$(uname -m) user=$(id -u) $(id -un)"
# Neither a dev venv nor /app layout (mis-copy or wrong cwd).
else
	echo "No venv at $SCRIPT_DIR/env and not an image layout (missing /app/app.py)." >&2
	exit 1
fi
cd "$APP_ROOT" || exit 1

run_dmz_pytest() {
	if [ "$RUNTIME_IS_CONTAINER" -eq 1 ]; then
		STARTUP_TESTS_LOG="/var/log/startup_tests.log"
		: >"$STARTUP_TESTS_LOG"
		printf '%s DMZ pytest starting\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$STARTUP_TESTS_LOG"
		if python -m pytest -q test >>"$STARTUP_TESTS_LOG" 2>&1; then
			printf '%s DMZ pytest finished (ok)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$STARTUP_TESTS_LOG"
		else
			printf '%s DMZ pytest finished (FAILED)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$STARTUP_TESTS_LOG"
			echo "FAILED pytest (see /var/log/startup_tests.log), app still starts"
		fi
	else
		printf '%s DMZ pytest starting\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
		python -m pytest -q test || echo "FAILED pytest, app still starts"
		printf '%s DMZ pytest finished (non-zero above means failure)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	fi
}

python_probe() {
	# Crash-only steps: SIGILL or import failure exits the process before the app.
	# Step labels go to /tmp/dmz-run.log AND stdout: run-with-stdout-logged only captures
	# stdout of this shell, so without echoing here you would see Python prints in
	# /var/log/dmz.log but not the "python_probe: done" line next to them.
	_probe_python_note "python_probe: step=hello_world"
	python -u -c "print('hello world', flush=True)"

	_probe_python_note "python_probe: step=import_platform"
	python -u -c "import platform; print('platform ok', flush=True)"

	_probe_python_note "python_probe: step=import_ssl"
	python -u -c "import ssl; print('ssl ok', flush=True)"

	_probe_python_note "python_probe: step=import_cryptography"
	python -u -c "import cryptography; print('cryptography ok', flush=True)"

	_probe_python_note "python_probe: step=import_pydantic_core"
	python -u -c "import importlib.util; spec=importlib.util.find_spec('pydantic_core'); print('pydantic_core ' + ('ok' if spec else 'absent'), flush=True)"

	_probe_python_note "python_probe: step=import_pydantic"
	python -u -c "import pydantic; print('pydantic ok', flush=True)"

	_probe_python_note "python_probe: step=import_app"
	python -u -c "print('about to import app', flush=True); import app; print('did import app', flush=True)"

	_probe_python_note "python_probe: done"
}

if [ "${DMZ_RUN_STARTUP_PYTEST:-}" = "1" ] || [ "${DMZ_RUN_STARTUP_PYTEST:-}" = "true" ] || [ "${DMZ_RUN_STARTUP_PYTEST:-}" = "yes" ]; then
	run_dmz_pytest
else
	echo "run.sh: skipping startup pytest (set DMZ_RUN_STARTUP_PYTEST=1 to run test/ before probes)"
fi

python_probe

_wait_flask_diagnostics() {
	_port="${PORT:-5000}"
	_tries=0
	while [ "$_tries" -lt 120 ]; do
		if python -u -c "
import sys
import urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:${_port}/ui/diagnostics', timeout=1)
except Exception:
    sys.exit(1)
sys.exit(0)
" 2>/dev/null; then
			echo "run.sh: Flask /ui/diagnostics ready on port ${_port}"
			return 0
		fi
		_tries=$((_tries + 1))
		sleep 0.5
	done
	echo "run.sh: WARNING Flask /ui/diagnostics not ready after 60s; starting ui_server anyway" >&2
	return 1
}

# Bundled thermo UI (proxies Flask on PORT) on UI_PORT — image has /app/ui; dev uses ../ui.
UI_SERVER_PATH="$APP_ROOT/ui/ui_server.py"
if [ ! -f "$UI_SERVER_PATH" ]; then
	UI_SERVER_PATH="$APP_ROOT/../ui/ui_server.py"
fi
if [ -f "$UI_SERVER_PATH" ]; then
	if [ -d "$APP_ROOT/heatpumpirctl" ]; then
		export PYTHONPATH="${APP_ROOT}${PYTHONPATH:+:$PYTHONPATH}"
	else
		export PYTHONPATH="${APP_ROOT}:${APP_ROOT}/../onboard${PYTHONPATH:+:$PYTHONPATH}"
	fi
	export THERMO_UI_BACKEND=dmz
	export UI_PORT="${UI_PORT:-8090}"
	# Flask must listen before ui_server: otherwise startup probes /ui/diagnostics fail and
	# GET / on UI_PORT serves HTML without hitting Flask (no werkzeug / access_log lines).
	echo "run.sh: starting Flask (PORT=${PORT:-5000}) before ui_server (UI_PORT=${UI_PORT})"
	python -u app.py &
	APP_PID=$!
	_wait_flask_diagnostics || true
	# If the HTML UI is on another public port than Flask (e.g. WAN :80 → ui_server), set
	# THERMO_UI_LOGIN_ORIGIN to the Flask base (no trailing slash), e.g. http://duck:5000
	python -u "$UI_SERVER_PATH" &
	UI_PID=$!
	wait "$APP_PID"
	_rc=$?
	kill "$UI_PID" 2>/dev/null || true
	wait "$UI_PID" 2>/dev/null || true
	exit "$_rc"
fi
# cwd is $APP_ROOT; relative app.py is enough (no need to repeat $APP_ROOT on the command line).
exec python -u app.py
