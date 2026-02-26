# common entry point, invoked by container, per Dockerfile
# Logs go to LOG_PATH (default /tmp/onboard.log), pruned by LOG_MAX_LINES.

# this hardcodes "this" onboard zone's name as zoneymczoneface
python twoway.py "http://onboard:5000/environment" "http://dmz:5000/zone/zoneymczoneface/sensors" "http://onboard:5000/daikin" &

echo "starting app"
python app.py
