# common entry point, invoked by container, per Dockerfile
# When run locally, asserts pip env exists.

hostname
whoami

echo dmz ENV "${ENV:-idk}"

if [ -f /.dockerenv ]; then
  exec python app.py
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
if [ ! -f "$SCRIPT_DIR/env/bin/activate" ]; then
  echo "No venv at $SCRIPT_DIR/env." >&2
  echo "Run: $UTILS_ROOT/create_pipenv.sh thermo/dmz" >&2
  exit 1
fi
. "$SCRIPT_DIR/env/bin/activate"
exec python app.py
