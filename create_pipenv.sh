#!/bin/sh
# Create virtualenv (.venv/) for one or more utils sub-projects.
# Each project gets utils/<path>/.venv with requirements.txt installed.
#
# Usage:
#   ./create_pipenv.sh [--sync|-s] PROJECT_PATH [PROJECT_PATH ...]
#
# Without --sync: skip projects whose .venv/ already exists (initial create only).
# With --sync: (re)install requirements into .venv/ even when it already exists.
#
# Examples:
#   ./create_pipenv.sh thermo/dmz thermo/onboard
#   ./create_pipenv.sh thermo/dmz
#   ./create_pipenv.sh --sync thermo/dmz
#
# Convention: utils/<project>/.venv (per-project). For jovlinger/bin/, use bin/setup-venv.sh -> bin/.venv.
# See utils/README.md.

set -e

SELF="$0"
case "$SELF" in
  */*) ;;
  *) SELF="$(command -v "$SELF")" ;;
esac
UTILS_ROOT="$(cd "$(dirname "$SELF")" && pwd)"

SYNC=0
while [ $# -gt 0 ]; do
  case "$1" in
  --sync | -s)
    SYNC=1
    shift
    ;;
  *)
    break
    ;;
  esac
done

if [ $# -eq 0 ]; then
  echo "Usage: $0 [--sync|-s] PROJECT_PATH [PROJECT_PATH ...]"
  echo ""
  echo "  PROJECT_PATH  Relative path from utils root (e.g. thermo/dmz, dedup)"
  echo "  --sync        Re-run pip install when .venv/ already exists"
  echo ""
  echo "Examples:"
  echo "  $0 thermo/dmz thermo/onboard"
  echo "  $0 thermo/dmz"
  echo "  $0 --sync thermo/dmz"
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1 && ! command -v python >/dev/null 2>&1; then
  echo "Python is not installed or not on PATH." >&2
  exit 1
fi

if [ -n "${VIRTUAL_ENV:-}" ]; then
  echo "Error: deactivate before create_pipenv (VIRTUAL_ENV=$VIRTUAL_ENV)." >&2
  echo "Project .venv must be created from system python3, not bin/.venv or another utils venv." >&2
  exit 1
fi

PYTHON_BIN="$(command -v python3 2>/dev/null || command -v python)"

for PROJECT_REL in "$@"; do
  PROJECT_DIR="$UTILS_ROOT/$PROJECT_REL"
  ENV_DIR="$PROJECT_DIR/.venv"
  LEGACY_ENV="$PROJECT_DIR/env"
  REQ_FILE="$PROJECT_DIR/requirements.txt"
  DEV_REQ="$PROJECT_DIR/requirements-dev.txt"

  if [ ! -d "$PROJECT_DIR" ]; then
    echo "Error: No such project $PROJECT_REL" >&2
    exit 1
  fi

  if [ -f "$LEGACY_ENV/bin/activate" ] && [ ! -f "$ENV_DIR/bin/activate" ]; then
    echo "Migrating legacy env/ -> .venv/ for $PROJECT_REL..."
    mv "$LEGACY_ENV" "$ENV_DIR"
  fi

  venv_has_python() {
    [ -x "$ENV_DIR/bin/python3" ] || [ -x "$ENV_DIR/bin/python" ]
  }

  # Subshell so activate does not leak into the rest of this script.
  run_pip_install() {
    (
      . "$ENV_DIR/bin/activate"
      if [ -f "$REQ_FILE" ]; then
        python -m pip install --upgrade pip -q
        python -m pip install -r "$REQ_FILE" -q
        echo "  Installed from $REQ_FILE"
      else
        echo "  No requirements.txt at $REQ_FILE"
      fi
      if [ -f "$DEV_REQ" ]; then
        python -m pip install -r "$DEV_REQ" -q
        echo "  Installed from $DEV_REQ"
      fi
    )
  }

  if [ -f "$ENV_DIR/bin/activate" ] && ! venv_has_python; then
    echo "Removing stale venv at $ENV_DIR (missing python executable)."
    rm -rf "$ENV_DIR"
  fi

  if [ -f "$ENV_DIR/bin/activate" ]; then
    if [ "$SYNC" -eq 1 ]; then
      echo "Syncing venv at $ENV_DIR..."
      run_pip_install
    else
      echo "Venv already exists at $ENV_DIR."
    fi
    continue
  fi

  echo "Creating venv at $ENV_DIR..."
  "$PYTHON_BIN" -m venv "$ENV_DIR"
  run_pip_install
done
