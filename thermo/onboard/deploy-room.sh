#!/bin/sh
# Resolve a room env file and dispatch through the onboard deployer.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO_PATH:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
THERMO_ROOT="$REPO/thermo"
export THERMO_ROOT

usage() {
	echo "usage: $0 <expected-backend> <room-env> [--deploy=true] [backend-args...]" >&2
	echo "examples:" >&2
	echo "  $0 pico2w office-pico2w.env" >&2
	echo "  $0 pico2w office-pico2w.env --deploy=true" >&2
	echo "  $0 pizero2w kitchen.env --deploy=true" >&2
}

if [ "$#" -lt 2 ]; then
	usage
	exit 2
fi

EXPECTED_ONBOARD_DEPLOY_BACKEND="$1"
ROOM_ENV="$2"
shift 2
THERMO_DEPLOY_EXECUTE=0
BACKEND_ARGS=""
while [ "$#" -gt 0 ]; do
	case "$1" in
	--deploy=true)
		THERMO_DEPLOY_EXECUTE=1
		;;
	--deploy=false)
		THERMO_DEPLOY_EXECUTE=0
		;;
	--deploy=*)
		echo "deploy-room: unsupported deploy flag: $1" >&2
		exit 2
		;;
	*)
		if [ -n "$BACKEND_ARGS" ]; then
			BACKEND_ARGS="$BACKEND_ARGS
$1"
		else
			BACKEND_ARGS="$1"
		fi
		;;
	esac
	shift
done

case "$ROOM_ENV" in
/*)
	THERMO_ENV_FILE="$ROOM_ENV"
	THERMO_ENV_PATH="$ROOM_ENV"
	;;
config/* | priv/*)
	THERMO_ENV_FILE="$ROOM_ENV"
	THERMO_ENV_PATH="$THERMO_ROOT/$ROOM_ENV"
	;;
*.env)
	THERMO_ENV_FILE="config/$ROOM_ENV"
	THERMO_ENV_PATH="$THERMO_ROOT/$THERMO_ENV_FILE"
	;;
*)
	THERMO_ENV_FILE="config/$ROOM_ENV.env"
	THERMO_ENV_PATH="$THERMO_ROOT/$THERMO_ENV_FILE"
	;;
esac

if [ ! -f "$THERMO_ENV_PATH" ]; then
	echo "deploy-room: env file not found: $THERMO_ENV_PATH" >&2
	exit 1
fi

export EXPECTED_ONBOARD_DEPLOY_BACKEND
export THERMO_DEPLOY_EXECUTE
export THERMO_ENV_FILE

if [ "$EXPECTED_ONBOARD_DEPLOY_BACKEND" = "pico2w" ] && [ "$THERMO_DEPLOY_EXECUTE" = "1" ]; then
	PICO2W_DEPLOY_ACTION=flash
	export PICO2W_DEPLOY_ACTION
fi

if [ -n "$BACKEND_ARGS" ]; then
	set -- $BACKEND_ARGS
else
	set --
fi

REPO_PATH="$REPO" /bin/sh "$THERMO_ROOT/onboard/install/deploy.sh" "$@"
