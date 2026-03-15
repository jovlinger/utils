#!/bin/sh
# Create virtualenv (env/) for one or more utils sub-projects.
# Each project gets utils/<path>/env with requirements.txt installed.
#
# Usage:
#   ./create_pipenv.sh [PROJECT_PATH ...]
#
# Examples:
#   ./create_pipenv.sh thermo/dmz thermo/onboard
#   ./create_pipenv.sh thermo/dmz
#
# Convention: one env per utils/<dir>/env. For bin/, use bin/setup-venv.sh.
# See utils/README.md.

set -e

SELF="$0"
case "$SELF" in
  */*) ;;
  *) SELF="$(command -v "$SELF")" ;;
esac
UTILS_ROOT="$(cd "$(dirname "$SELF")" && pwd)"

if [ $# -eq 0 ]; then
  echo "Usage: $0 PROJECT_PATH [PROJECT_PATH ...]"
  echo ""
  echo "  PROJECT_PATH  Relative path from utils root (e.g. thermo/dmz, dedup)"
  echo ""
  echo "Examples:"
  echo "  $0 thermo/dmz thermo/onboard"
  echo "  $0 thermo/dmz"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  echo "Python is not installed or not on PATH." >&2
  exit 1
fi
PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python)"

for PROJECT_REL in "$@"; do
  ENV_DIR="$UTILS_ROOT/$PROJECT_REL/env"
  REQ_FILE="$UTILS_ROOT/$PROJECT_REL/requirements.txt"

  if [ -f "$ENV_DIR/bin/activate" ]; then
    echo "Venv already exists at $ENV_DIR."
    continue
  fi

  if [ ! -d "$UTILS_ROOT/$PROJECT_REL" ]; then
    echo "Error: No such project $PROJECT_REL" >&2
    exit 1
  fi

  echo "Creating venv at $ENV_DIR..."
  "$PYTHON_BIN" -m venv "$ENV_DIR"
  (
    . "$ENV_DIR/bin/activate"
    if [ -f "$REQ_FILE" ]; then
      python -m pip install --upgrade pip -q
      python -m pip install -r "$REQ_FILE" -q
      echo "  Installed from $REQ_FILE"
    else
      echo "  No requirements.txt at $REQ_FILE"
    fi
  )
done
