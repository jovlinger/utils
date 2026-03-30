#!/bin/sh
# Creates the repo-local venv and installs requirements.txt if present.
# Safe to run from any directory; it resolves its own path.
set -eu

SELF="$0"
case "$SELF" in
  */*) ;;
  *) SELF="$(command -v "$SELF")" ;;
esac
# If invoked via $PATH, resolve the real file so we can locate the repo root.
SCRIPT_DIR="$(cd "$(dirname "$SELF")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
REQ_FILE="$SCRIPT_DIR/requirements.txt"

if [ -f "$VENV_DIR/bin/activate" ]; then
  echo "Venv already exists at $VENV_DIR."
  exit 0
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
else
  echo "Python is not installed or not on PATH." >&2
  exit 1
fi

"$PYTHON_BIN" -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"

if [ -f "$REQ_FILE" ]; then
  python -m pip install --upgrade pip
  python -m pip install -r "$REQ_FILE"
else
  echo "No requirements.txt found at $REQ_FILE."
  echo "Create one or install dependencies manually."
fi
