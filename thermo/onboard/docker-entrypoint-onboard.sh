#!/bin/sh
# Onboard app container: ui_server (background) + Flask app (foreground, log wrapper).
# Logs only under LOG_DIR via run-with-stdout-logged (rotation in wrapper).
set -eu

LOG_DIR="${LOG_DIR:-/var/log/thermo-onboard}"
LOG_PATH_APP="${LOG_PATH_APP:-$LOG_DIR/onboard-app.log}"
LOG_PATH_UI="${LOG_PATH_UI:-$LOG_DIR/onboard-ui.log}"
LOG_FILELIMIT="${LOG_FILELIMIT:-1048576}"
LOG_TOTALLIMIT="${LOG_TOTALLIMIT:-2097152}"

mkdir -p "$(dirname "$LOG_PATH_APP")" "$(dirname "$LOG_PATH_UI")"

# app.py /manage reports this path
export LOG_PATH="$LOG_PATH_APP"

# Background UI: same rotation wrapper so nothing grows unbounded on Docker's json log.
python ./bin/run-with-stdout-logged.py "$LOG_PATH_UI" "$LOG_FILELIMIT" "$LOG_TOTALLIMIT" \
  python ui_server.py &
exec python ./bin/run-with-stdout-logged.py "$LOG_PATH_APP" "$LOG_FILELIMIT" "$LOG_TOTALLIMIT" \
  python app.py
