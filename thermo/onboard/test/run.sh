#!/bin/bash
# Run all onboard-related tests: unit tests, UI integration, daikin integration.
# Uses thermo/onboard/env venv and requirements.txt.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONBOARD="$(cd "$SCRIPT_DIR/.." && pwd)"
THERMO="$(cd "$ONBOARD/.." && pwd)"

cd "$ONBOARD"
if [ ! -d env ]; then
    python3 -m venv env
    env/bin/pip install -r requirements.txt
fi
"$ONBOARD/env/bin/python" -m unittest discover -s test -p 'test_*.py'

bash "$SCRIPT_DIR/test_ui.sh"

cd "$THERMO"
bash test/daikin/test-daikin-send.sh
bash test/daikin/test-daikin-recv.sh
