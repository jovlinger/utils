#!/bin/sh
# Shared launcher for Python modules in this repo. It is symlinked under
# command names like "clean" or "shadup" and uses that name to run
# "python -m <name>" after activating the local venv.
set -eu

SELF="$0"
case "$SELF" in
  */*) ;;
  *) SELF="$(command -v "$SELF")" ;;
esac
# If invoked via $PATH, resolve the real file so we can locate the repo root.
SCRIPT_DIR="$(cd "$(dirname "$SELF")" && pwd)"
CMD_NAME="$(basename "$0")"
VENV_DIR="$SCRIPT_DIR/.venv"
SETUP_VENV="$SCRIPT_DIR/setup-venv.sh"

read_min_python_version() {
  MIN_MAJOR=3
  MIN_MINOR=10
  if [ -f "$SETUP_VENV" ]; then
    line=$(grep '^MIN_MAJOR=' "$SETUP_VENV" 2>/dev/null || true)
    if [ -n "$line" ]; then
      MIN_MAJOR=${line#MIN_MAJOR=}
    fi
    line=$(grep '^MIN_MINOR=' "$SETUP_VENV" 2>/dev/null || true)
    if [ -n "$line" ]; then
      MIN_MINOR=${line#MIN_MINOR=}
    fi
  fi
}

venv_python_bin() {
  if [ -x "$VENV_DIR/bin/python3" ] || [ -L "$VENV_DIR/bin/python3" ]; then
    echo "$VENV_DIR/bin/python3"
  elif [ -x "$VENV_DIR/bin/python" ] || [ -L "$VENV_DIR/bin/python" ]; then
    echo "$VENV_DIR/bin/python"
  else
    return 1
  fi
}

print_recreate_instructions() {
  if [ -f "$SETUP_VENV" ]; then
    echo "  rm -rf \"$VENV_DIR\" && \"$SETUP_VENV\"" >&2
  else
    echo "  rm -rf \"$VENV_DIR\"   # then recreate a venv with Python >= ${MIN_MAJOR}.${MIN_MINOR}" >&2
  fi
}

# PEP 604 unions in annotations (for example `list[str] | None`) are evaluated
# at import time on Python < 3.10 and raise:
#   TypeError: unsupported operand type(s) for |: 'types.GenericAlias' and 'NoneType'
diagnose_pep604_union_typeerror() {
  errfile=$1
  venv_python=$2

  if ! grep -Fq "unsupported operand type(s) for |:" "$errfile"; then
    return 1
  fi
  if ! grep -Fq "'types.GenericAlias' and 'NoneType'" "$errfile"; then
    return 1
  fi

  read_min_python_version

  py_full=$("$venv_python" -c 'import sys; print("%d.%d.%d" % sys.version_info[:3])' 2>/dev/null || echo "unknown")
  py_short=$("$venv_python" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "unknown")
  py_exe=$("$venv_python" -c 'import sys; print(sys.executable)' 2>/dev/null || echo "$venv_python")

  err_line=""
  err_file=""
  err_file=$(grep -E '^  File "' "$errfile" | tail -1 | sed -n 's/^  File "\([^"]*\)", line \([0-9]*\).*/\1:\2/p')
  err_line=$(grep -E 'def .+\|.+' "$errfile" | tail -1 | sed 's/^[[:space:]]*//')

  echo "" >&2
  echo "Diagnosis: stale or incompatible venv for $CMD_NAME." >&2
  echo "" >&2
  echo "  What failed:" >&2
  echo "    Python raised TypeError while evaluating a PEP 604 union type" >&2
  echo "    annotation (the \`|\` operator in a type hint, e.g. list[str] | None)." >&2
  if [ -n "$err_file" ]; then
    echo "    Location: $err_file" >&2
  fi
  if [ -n "$err_line" ]; then
    echo "    Code: $err_line" >&2
  fi
  echo "" >&2
  echo "  Why:" >&2
  echo "    That syntax requires Python >= ${MIN_MAJOR}.${MIN_MINOR}." >&2
  echo "    This venv is running Python $py_full ($py_exe)." >&2

  if [ -L "$VENV_DIR/bin/python3" ]; then
    py_link=$(readlink "$VENV_DIR/bin/python3" 2>/dev/null || true)
    case "$py_link" in
      "$VENV_DIR"/*) ;;
      *)
        if [ -n "$py_link" ]; then
          echo "    $VENV_DIR/bin/python3 is symlinked to $py_link (not a standalone venv)." >&2
        fi
        ;;
    esac
  fi

  if ! "$venv_python" -c "import os, sys; sys.exit(0 if os.path.realpath(sys.prefix) == os.path.realpath('$VENV_DIR') else 1)" >/dev/null 2>&1; then
    venv_prefix=$("$venv_python" -c 'import sys; print(sys.prefix)' 2>/dev/null || echo "?")
    echo "    sys.prefix is $venv_prefix, not $VENV_DIR." >&2
  fi

  if [ -f "$SETUP_VENV" ] && [ -f "$VENV_DIR/bin/activate" ]; then
    echo "    $SETUP_VENV will not recreate the venv while .venv already exists." >&2
  fi

  echo "" >&2
  echo "  Fix: remove the venv and recreate it with a newer Python:" >&2
  print_recreate_instructions
  return 0
}

if [ ! -f "$VENV_DIR/bin/activate" ]; then
  echo "No local venv found at $VENV_DIR." >&2
  echo "Run: $SETUP_VENV" >&2
  echo "Or create a Pipenv and install dependencies." >&2
  exit 1
fi

venv_python=$(venv_python_bin) || {
  echo "No python executable found in $VENV_DIR/bin/." >&2
  echo "Run: $SETUP_VENV" >&2
  exit 1
}

. "$VENV_DIR/bin/activate"

PYTHONPATH="$SCRIPT_DIR${PYTHONPATH:+:$PYTHONPATH}"
export PYTHONPATH

tmpdir=${TMPDIR:-/tmp}
if [ ! -d "$tmpdir" ]; then
  tmpdir=/tmp
fi
errfile=$(mktemp "$tmpdir/pylauncher.XXXXXX") || exit 1
# shellcheck disable=SC2064
trap 'rm -f "$errfile"' EXIT INT HUP TERM

if "$venv_python" -m "$CMD_NAME" "$@" 2>"$errfile"; then
  rm -f "$errfile"
  trap - EXIT INT HUP TERM
  exit 0
fi

cat "$errfile" >&2
diagnose_pep604_union_typeerror "$errfile" "$venv_python" || true
exit 1
