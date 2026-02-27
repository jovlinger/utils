#!/bin/bash
# Run DMZ tests: unit tests and happy-path integration tests.
# Uses thermo/dmz env venv and requirements.txt.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DMZ="$(cd "$SCRIPT_DIR/.." && pwd)"

cd "$DMZ"
if [ ! -d env ]; then
    python3 -m venv env
    env/bin/pip install -r requirements.txt
fi
"$DMZ/env/bin/python" -m unittest discover -s test -p 'test_*.py'
