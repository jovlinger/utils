#!/bin/bash

# This is the command-line test driver.
# This composes a docker container and runs it. This is run OUTSIDE the container

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
THERMO="$(cd "$SCRIPT_DIR/.." && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# gen_keys.py needs zone_auth (thermo/dmz) or thermo/test deps
if [ ! -f "$THERMO/test/env/bin/activate" ] && [ ! -f "$THERMO/dmz/env/bin/activate" ]; then
  echo "No venv at thermo/test/env or thermo/dmz/env." >&2
  echo "Run: $UTILS_ROOT/create_pipenv.sh thermo/test thermo/dmz" >&2
  exit 1
fi

# Generate Ed25519 keys for machine auth (twoway -> dmz)
mkdir -p keys
if [ -f "$THERMO/test/env/bin/python" ]; then
  "$THERMO/test/env/bin/python" gen_keys.py 2>/dev/null || true
elif [ -f "$THERMO/dmz/env/bin/python" ]; then
  "$THERMO/dmz/env/bin/python" gen_keys.py 2>/dev/null || true
fi

# | cat to convince the script that we are not a tty, and to skip the color and redraws
docker compose up --timestamps --abort-on-container-exit --always-recreate-deps --build --exit-code-from  testdriver 2>&1  | cat
