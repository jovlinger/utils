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
  if [ -x "$VENV_DIR/bin/python3" ] || [ -x "$VENV_DIR/bin/python" ]; then
    echo "Venv already exists at $VENV_DIR."
    exit 0
  fi
  echo "Removing stale venv at $VENV_DIR (missing python executable)."
  rm -rf "$VENV_DIR"
fi

# Need Python >= 3.10 (shadup.py uses PEP 604 "X | None" syntax).
MIN_MAJOR=3
MIN_MINOR=10

PYTHON_BIN=""
# Prefer explicit versioned binaries (newest first), then fall back to
# generic python3/python if their reported version is recent enough.
for candidate in \
  python3.13 python3.12 python3.11 python3.10 \
  python3 python; do
  if command -v "$candidate" >/dev/null 2>&1; then
    ver="$("$candidate" -c 'import sys; print("%d %d" % sys.version_info[:2])' 2>/dev/null || echo "")"
    if [ -n "$ver" ]; then
      maj="${ver% *}"
      min="${ver#* }"
      if [ "$maj" -gt "$MIN_MAJOR" ] || \
         { [ "$maj" -eq "$MIN_MAJOR" ] && [ "$min" -ge "$MIN_MINOR" ]; }; then
        PYTHON_BIN="$candidate"
        break
      fi
    fi
  fi
done

if [ -z "$PYTHON_BIN" ]; then
  echo "No Python >= ${MIN_MAJOR}.${MIN_MINOR} found on PATH." >&2
  echo "Install a recent Python, e.g.:" >&2
  if command -v brew >/dev/null 2>&1; then
    echo "  brew install python@3.12" >&2
  elif command -v apt-get >/dev/null 2>&1; then
    echo "  sudo apt-get install python3.12 python3.12-venv" >&2
  elif command -v dnf >/dev/null 2>&1; then
    echo "  sudo dnf install python3.12" >&2
  else
    echo "  (use your platform's package manager to install python>=${MIN_MAJOR}.${MIN_MINOR})" >&2
  fi
  exit 1
fi

echo "Using $PYTHON_BIN ($("$PYTHON_BIN" --version 2>&1)) to create venv."
"$PYTHON_BIN" -m venv "$VENV_DIR"
. "$VENV_DIR/bin/activate"

if [ -f "$REQ_FILE" ]; then
  python -m pip install --upgrade pip
  python -m pip install -r "$REQ_FILE"
else
  echo "No requirements.txt found at $REQ_FILE."
  echo "Create one or install dependencies manually."
fi
