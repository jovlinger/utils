#!/bin/sh
# Back-compat wrapper: map legacy env filenames to zones/<zone> make deploy.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO_PATH:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

usage() {
	echo "usage: $0 <expected-backend> <room-env> [--deploy=true]" >&2
	echo "examples:" >&2
	echo "  $0 pico2w office-pico2w.env" >&2
	echo "  $0 pico2w office-pico2w.env --deploy=true" >&2
	echo "  $0 pizero2w kitchen.env --deploy=true" >&2
	echo "preferred: make -C thermo/onboard/zones/office deploy [THERMO_DEPLOY_EXECUTE=1]" >&2
}

if [ "$#" -lt 2 ]; then
	usage
	exit 2
fi

EXPECTED="$1"
ROOM_ENV="$2"
shift 2
THERMO_DEPLOY_EXECUTE=0
while [ "$#" -gt 0 ]; do
	case "$1" in
	--deploy=true) THERMO_DEPLOY_EXECUTE=1 ;;
	--deploy=false) THERMO_DEPLOY_EXECUTE=0 ;;
	--deploy=*)
		echo "deploy-room: unsupported deploy flag: $1" >&2
		exit 2
		;;
	esac
	shift
done

case "$ROOM_ENV" in
kitchen.env | kitchen | zones/kitchen/zone.env) ZONE=kitchen ;;
office-pico2w.env | office | zones/office/zone.env) ZONE=office ;;
bedroom-pico2w.env | bedroom | zones/bedroom/zone.env) ZONE=bedroom ;;
*)
	echo "deploy-room: unknown room env: $ROOM_ENV" >&2
	exit 1
	;;
esac

exec make -C "$SCRIPT_DIR/zones/$ZONE" deploy \
	EXPECTED_ONBOARD_DEPLOY_BACKEND="$EXPECTED" \
	THERMO_DEPLOY_EXECUTE="$THERMO_DEPLOY_EXECUTE" \
	REPO_PATH="$REPO"
