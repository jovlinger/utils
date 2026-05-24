#!/bin/sh
# Compatibility wrapper: install the selected hardware backend's systemd unit.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO_PATH:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"
BACKEND="${ONBOARD_DEPLOY_BACKEND:-pizero2w}"
BACKEND_INSTALL="$REPO/thermo/onboard/hardware/$BACKEND/install/install-systemd.sh"

if [ ! -f "$BACKEND_INSTALL" ]; then
	echo "install-systemd: missing backend installer: $BACKEND_INSTALL" >&2
	exit 1
fi

/bin/sh "$BACKEND_INSTALL" "$@"
