# shellcheck shell=sh
# Resolve and source a thermo env file. Source this script (do not execute).
#
# Required environment:
#   THERMO_ROOT     — absolute path to the thermo/ directory
#   THERMO_ENV_FILE — path relative to thermo/ (e.g. config/kitchen.env) or absolute
#
# Naming: we use THERMO_ENV_FILE because ENV is reserved for app runtime (DOCKERTEST, TEST, …).

: "${THERMO_ROOT:?thermo: THERMO_ROOT is not set}"
: "${THERMO_ENV_FILE:?thermo: set THERMO_ENV_FILE (e.g. export THERMO_ENV_FILE=config/kitchen.env)}"

case "$THERMO_ENV_FILE" in
/*) _THERMO_ENV_PATH="$THERMO_ENV_FILE" ;;
*) _THERMO_ENV_PATH="$THERMO_ROOT/$THERMO_ENV_FILE" ;;
esac

if [ ! -f "$_THERMO_ENV_PATH" ]; then
	echo "thermo: env file not found: $_THERMO_ENV_PATH" >&2
	exit 1
fi

# shellcheck source=/dev/null
. "$_THERMO_ENV_PATH"
