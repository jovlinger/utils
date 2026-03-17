#!/bin/bash
# Run DMZ tests: unit tests and happy-path integration tests.
# Uses thermo/dmz env venv and requirements.txt.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DMZ="$(cd "$SCRIPT_DIR/.." && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

if [ ! -f "$DMZ/env/bin/activate" ]; then
  echo "No venv at $DMZ/env." >&2
  echo "Run: $UTILS_ROOT/create_pipenv.sh thermo/dmz" >&2
  exit 1
fi

cd "$DMZ"
. "$DMZ/env/bin/activate"
python -m unittest discover -s test -p 'test_*.py'
