#!/bin/sh
# Deploy a Pi Zero 2 W room manifest from this hardware directory.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /bin/sh "$SCRIPT_DIR/../../deploy-room.sh" pizero2w "$@"
