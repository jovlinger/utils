# Invoked by start.sh as user `dmz` in the container, or directly with a venv on a dev machine.
# Pi chroot matches the image layout (/app/...) but has no /.dockerenv — same runtime path as Docker.
#
# Runs unittest (test/*.py, non-fatal if it fails) then import/smoke probes, then the app.

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

run_dmz_unittest() {
	# Stdlib unittest only (no pytest in the runtime image). Smoketest stays host-side (smoketest/run.sh).
	if [ "$RUNTIME_IS_CONTAINER" -eq 1 ]; then
		STARTUP_TESTS_LOG="/var/log/startup_tests.log"
		: >"$STARTUP_TESTS_LOG"
		printf '%s DMZ unittest starting\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$STARTUP_TESTS_LOG"
		if python -m unittest discover -s test -p 'test_*.py' -q >>"$STARTUP_TESTS_LOG" 2>&1; then
			printf '%s DMZ unittest finished (ok)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$STARTUP_TESTS_LOG"
		else
			printf '%s DMZ unittest finished (FAILED)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$STARTUP_TESTS_LOG"
			echo "FAILED unittest (see /var/log/startup_tests.log), app still starts"
		fi
	else
		printf '%s DMZ unittest starting\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
		python -m unittest discover -s test -p 'test_*.py' -q || echo "FAILED unittest, app still starts"
		printf '%s DMZ unittest finished (non-zero above means failure)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
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

run_dmz_unittest
python_probe
# cwd is $APP_ROOT; relative app.py is enough (no need to repeat $APP_ROOT on the command line).
exec python -u app.py
