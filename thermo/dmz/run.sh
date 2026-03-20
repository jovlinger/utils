# common entry point, invoked by container, per Dockerfile
# When run for real (by install/run_raw.sh), asserts pip env exists.
#
# Temporary: run pytest before the app (Pi / smoke). To be removed in favor of
# Docker-based fidelity tests — see discussion in repo.

hostname
whoami

echo dmz ENV "${ENV:-idk}"

DMZ_LOG="/var/log/dmz.log"


# Same interpreter as `exec python app.py` below (image: python→python3; venv: activated python).
run_dmz_pytest() {
    printf '%s DMZ pytest starting\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    python -m pytest -q || echo "FAILED pytest, app still starts"
    printf '%s DMZ pytest finished (non-zero above means failure)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

python_probe() {
    # Crash-only probes: SIGILL will terminate the process. We rely on
    # run-with-stdout-logged.py to append the child returncode/signal line.
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
    # run_dmz_pytest
    echo "run.sh: preflight (docker) uname -m=$(uname -m)"
    # Avoid importing/running Python-based probes here; exec below may SIGILL.
    printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "run.sh: preflight (docker) uname -m=$(uname -m)" >>"$DMZ_LOG"
    python_probe
    exec python app.py
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ ! -f "$SCRIPT_DIR/env/bin/activate" ]; then
    echo "No venv at $SCRIPT_DIR/env." >&2
    echo "Run: $UTILS_ROOT/create_pipenv.sh thermo/dmz" >&2
    exit 1
fi
# shellcheck source=/dev/null
. "$SCRIPT_DIR/env/bin/activate"
# run_dmz_pytest
echo "run.sh: preflight uname -m=$(uname -m) uname=$(uname -a)"
printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "run.sh: preflight uname -m=$(uname -m) uname=$(uname -a)" >>"$DMZ_LOG"
case "$(uname -m)" in
    armv6*|armv6l) echo "run.sh: preflight armv6=yes" ;;
    *) echo "run.sh: preflight armv6=no (ISA mismatch likely)" ;;
esac
if [ -r /proc/cpuinfo ]; then
    echo "run.sh: preflight /proc/cpuinfo head:"
    head -n 12 /proc/cpuinfo
fi
echo "run.sh: preflight python=$(command -v python 2>/dev/null || true)"
printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "run.sh: preflight python=$(command -v python 2>/dev/null || true)" >>"$DMZ_LOG"
python_probe
echo "run.sh: preflight python_probe done, app starting"
exec python app.py
