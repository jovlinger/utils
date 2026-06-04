#!/bin/bash
# Run all onboard-related tests: unit tests, UI integration, daikin integration.
# Uses the nearest thermo/onboard venv marker and requirements.txt.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONBOARD="$(cd "$SCRIPT_DIR/.." && pwd)"
THERMO="$(cd "$ONBOARD/.." && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# shellcheck source=/dev/null
. "$UTILS_ROOT/lib/venv-resolve.sh"
resolve_utils_venv "$ONBOARD" "$UTILS_ROOT"

cd "$ONBOARD"
# shellcheck source=/dev/null
. "$VENV_DIR/bin/activate"
pytest -q test

bash "$SCRIPT_DIR/test_ui.sh"

cd "$THERMO"
bash test/daikin/test-daikin-send.sh
bash test/daikin/test-daikin-recv.sh
