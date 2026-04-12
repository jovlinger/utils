#!/bin/bash
# Run all onboard-related tests: unit tests, UI integration, daikin integration.
# Uses thermo/onboard/env venv and requirements.txt.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONBOARD="$(cd "$SCRIPT_DIR/.." && pwd)"
THERMO="$(cd "$ONBOARD/.." && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

if [ ! -f "$ONBOARD/env/bin/activate" ]; then
  echo "No venv at $ONBOARD/env." >&2
  echo "Run: $UTILS_ROOT/create_pipenv.sh thermo/onboard" >&2
  exit 1
fi

cd "$ONBOARD"
. "$ONBOARD/env/bin/activate"
python -m pytest -q test

bash "$SCRIPT_DIR/test_ui.sh"

cd "$THERMO"
bash test/daikin/test-daikin-send.sh
bash test/daikin/test-daikin-recv.sh
