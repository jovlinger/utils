# Invoked by start.sh as user `dmz` in the container, or directly with a venv on a dev machine.
#
# Runs unittest (test/*.py, non-fatal if it fails) then import/smoke probes, then the app.

hostname
whoami

echo "dmz ENV ${ENV:-idk}"

# Probe breadcrumbs (works in Docker and local dev without /var/log).
DMZ_LOG="/tmp/dmz-run.log"

run_dmz_unittest() {
	# Stdlib unittest only (no pytest in the runtime image). Smoketest stays host-side (smoketest/run.sh).
	if [ -f /.dockerenv ]; then
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

run_dmz_unittest
python_probe
exec python -u app.py
