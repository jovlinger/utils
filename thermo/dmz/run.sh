# common entry point, invoked by container, per Dockerfile
# When run for real (by install/run_raw.sh), asserts pip env exists.
#
# Temporary: run pytest before the app (Pi / smoke). To be removed in favor of
# Docker-based fidelity tests — see discussion in repo.

hostname
whoami

echo dmz ENV "${ENV:-idk}"



# Same interpreter as `exec python app.py` below (image: python→python3; venv: activated python).
run_dmz_pytest() {
    printf '%s DMZ pytest starting\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    python -m pytest -q || echo "FAILED pytest, app still starts"
    printf '%s DMZ pytest finished (non-zero above means failure)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}

python_probe() {
    # Crash-only probes: SIGILL will terminate the process. We rely on
    # run-with-stdout-logged.py to append the child returncode/signal line.
    echo "python_probe: step=hello_world"
    python -c "print('hello world')"

    echo "python_probe: step=import_platform"
    python -c "import platform; print('platform ok')"

    echo "python_probe: step=import_ssl"
    python -c "import ssl; print('ssl ok')"

    echo "python_probe: step=import_cryptography"
    python -c "import cryptography; print('cryptography ok')"
    echo "python_probe: done"
}

if [ -f /.dockerenv ]; then
    # run_dmz_pytest
    echo "run.sh: preflight (docker) uname -m=$(uname -m)"
    # Avoid importing/running Python-based probes here; exec below may SIGILL.
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
case "$(uname -m)" in
    armv6*|armv6l) echo "run.sh: preflight armv6=yes" ;;
    *) echo "run.sh: preflight armv6=no (ISA mismatch likely)" ;;
esac
if [ -r /proc/cpuinfo ]; then
    echo "run.sh: preflight /proc/cpuinfo head:"
    head -n 12 /proc/cpuinfo
fi
echo "run.sh: preflight python=$(command -v python 2>/dev/null || true)"
python_probe
exec python app.py
