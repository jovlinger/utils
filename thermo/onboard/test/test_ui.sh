#!/usr/bin/env bash
# Test the UI server: GET renders form with env, POST form sends to app.
# Uses fake ir-ctl from thermo/test/daikin so send_daikin_state runs the full path.
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ONBOARD="$(cd "$SCRIPT_DIR/.." && pwd)"
THERMO="$(cd "$ONBOARD/.." && pwd)"
FAKE_IRCTL_DIR="$THERMO/test/daikin"
# Use high ports to avoid conflicts; 5xxxx range often free
PORT_APP=$((50000 + RANDOM % 1000))
PORT_UI=$((51000 + RANDOM % 1000))
PYTHON="${PYTHON:-${ONBOARD}/env/bin/python}"
[ -x "$PYTHON" ] || PYTHON=python3

cd "$ONBOARD"

# Fake ir-ctl at head of PATH so send_daikin_state invokes it instead of real ir-ctl
export PATH="${FAKE_IRCTL_DIR}:${PATH}"

# Start app in background
PORT=$PORT_APP ENV=TEST "$PYTHON" app.py &
APP_PID=$!
trap 'kill $APP_PID $UI_PID 2>/dev/null || true' EXIT

sleep 2
kill -0 $APP_PID 2>/dev/null || { echo "FAIL: app did not start"; exit 1; }

# Start UI server in background
PORT=$PORT_APP UI_PORT=$PORT_UI ENV=TEST "$PYTHON" ui_server.py &
UI_PID=$!
trap 'kill $APP_PID $UI_PID 2>/dev/null || true' EXIT

sleep 1
kill -0 $UI_PID 2>/dev/null || { echo "FAIL: ui_server did not start"; exit 1; }

# GET: must contain form and env
GET_OUT=$(curl -s --connect-timeout 2 "http://127.0.0.1:$PORT_UI/")
echo "$GET_OUT" | grep -q '<form method="post"' || { echo "FAIL: GET missing form"; exit 1; }
echo "$GET_OUT" | grep -q 'Environment:' || { echo "FAIL: GET missing Environment"; exit 1; }
echo "$GET_OUT" | grep -q 'SEND' || { echo "FAIL: GET missing SEND button"; exit 1; }

# POST: must return success message and repopulated form
POST_OUT=$(curl -s --connect-timeout 2 -X POST "http://127.0.0.1:$PORT_UI/" -d "power=on&mode=HEAT&temp_c=22&fan=AUTO")
echo "$POST_OUT" | grep -qE 'Sent\.|Stored\.' || { echo "FAIL: POST missing Sent/Stored"; exit 1; }
echo "$POST_OUT" | grep -q 'value="22.0"' || { echo "FAIL: POST form not repopulated with temp"; exit 1; }
echo "$POST_OUT" | grep -q 'HEAT.*selected' || { echo "FAIL: POST form not repopulated with mode"; exit 1; }

# Environment must refresh after POST: inject new readings, POST, verify response shows them
curl -s -X POST "http://127.0.0.1:$PORT_APP/test/inject_readings" -H "Content-Type: application/json" -d '{"temp_centigrade":18.5,"humid_percent":62}' >/dev/null
POST2_OUT=$(curl -s --connect-timeout 2 -X POST "http://127.0.0.1:$PORT_UI/" -d "power=on&mode=COOL&temp_c=24&fan=AUTO")
echo "$POST2_OUT" | grep -q '18.5°C, 62%' || { echo "FAIL: POST response Environment not refreshed (expected 18.5°C, 62%)"; echo "$POST2_OUT" | head -5; exit 1; }

echo "PASS: UI GET and POST OK"
