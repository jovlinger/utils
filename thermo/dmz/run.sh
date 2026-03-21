# Invoked by start.sh as user `dmz` in the container, or directly with a venv on a dev machine.
#
# Always runs pytest (non-fatal if it fails) then import/smoke probes, then the app.

hostname
whoami

echo "dmz ENV ${ENV:-idk}"

# Probe breadcrumbs (works in Docker and local dev without /var/log).
DMZ_LOG="/tmp/dmz-run.log"

run_dmz_pytest() {
	# pytest.ini limits collection to test/; smoketest/ needs a live server (smoketest/run.sh).
	# In Docker, send full pytest output to a file so /var/log/dmz.log stays readable (run.sh + app).
	if [ -f /.dockerenv ]; then
		STARTUP_PYTEST_LOG="/var/log/startup_pytest.log"
		: >"$STARTUP_PYTEST_LOG"
		printf '%s DMZ pytest starting\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$STARTUP_PYTEST_LOG"
		if pytest -q >>"$STARTUP_PYTEST_LOG" 2>&1; then
			printf '%s DMZ pytest finished (ok)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$STARTUP_PYTEST_LOG"
		else
			printf '%s DMZ pytest finished (FAILED)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >>"$STARTUP_PYTEST_LOG"
			echo "FAILED pytest (see /var/log/startup_pytest.log), app still starts"
		fi
	else
		printf '%s DMZ pytest starting\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
		pytest -q || echo "FAILED pytest, app still starts"
		printf '%s DMZ pytest finished (non-zero above means failure)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	fi
}

python_probe() {
	# Crash-only steps: SIGILL or import failure exits the process before the app.
	printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "python_probe: step=hello_world" >>"$DMZ_LOG"
	python -u -c "print('hello world', flush=True)"

	printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "python_probe: step=import_platform" >>"$DMZ_LOG"
	python -u -c "import platform; print('platform ok', flush=True)"

	printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "python_probe: step=import_ssl" >>"$DMZ_LOG"
	python -u -c "import ssl; print('ssl ok', flush=True)"

	printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "python_probe: step=import_cryptography" >>"$DMZ_LOG"
	python -u -c "import cryptography; print('cryptography ok', flush=True)"

	printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "python_probe: step=import_pydantic_core" >>"$DMZ_LOG"
	python -u -c "import importlib.util; spec=importlib.util.find_spec('pydantic_core'); print('pydantic_core ' + ('ok' if spec else 'absent'), flush=True)"

	printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "python_probe: step=import_pydantic" >>"$DMZ_LOG"
	python -u -c "import pydantic; print('pydantic ok', flush=True)"

	printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "python_probe: step=import_app" >>"$DMZ_LOG"
	python -u -c "print('about to import app', flush=True); import app; print('did import app', flush=True)"

	printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "python_probe: done" >>"$DMZ_LOG"
}

if [ -f /.dockerenv ]; then
	echo "run.sh: docker uname -m=$(uname -m) user=$(id -u) $(id -un)"
else
	SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
	UTILS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
	if [ ! -f "$SCRIPT_DIR/env/bin/activate" ]; then
		echo "No venv at $SCRIPT_DIR/env." >&2
		echo "Run: $UTILS_ROOT/create_pipenv.sh thermo/dmz" >&2
		exit 1
	fi
	# shellcheck source=/dev/null
	. "$SCRIPT_DIR/env/bin/activate"
	echo "run.sh: dev uname -m=$(uname -m)"
fi

run_dmz_pytest
python_probe
exec python -u app.py
