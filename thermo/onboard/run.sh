# common entry point, invoked by container, per Dockerfile
# Logs go to LOG_PATH (default /tmp/onboard.log), pruned by LOG_MAX_LINES.

# this hardcodes "this" onboard zone's name as zoneymczoneface
# Use 127.0.0.1 for onboard (host network has no Docker DNS). Override ONBOARD_URL/DMZ_URL for docker-compose.
ONBOARD="${ONBOARD_URL:-http://127.0.0.1:5000}"
DMZ="${DMZ_URL:-http://dmz:5000}"
python twoway.py "${ONBOARD}/environment" "${DMZ}/zone/zoneymczoneface/sensors" "${ONBOARD}/daikin" &

python ui_server.py &

echo "starting app"
python app.py
