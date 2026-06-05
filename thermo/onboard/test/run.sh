#!/bin/bash
# Run all onboard-related tests: unit tests, UI integration, daikin integration.
# Uses the thermo/onboard venv pytest directly.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONBOARD="$(cd "$SCRIPT_DIR/.." && pwd)"
THERMO="$(cd "$ONBOARD/.." && pwd)"

cd "$ONBOARD"
"$ONBOARD/.venv/bin/pytest" -q test

bash "$SCRIPT_DIR/test_ui.sh"

cd "$THERMO"
bash test/daikin/test-daikin-send.sh
bash test/daikin/test-daikin-recv.sh
