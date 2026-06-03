#!/bin/sh
# Deploy a Pico2W room manifest from this hardware directory.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec /bin/sh "$SCRIPT_DIR/../../deploy-room.sh" pico2w "$@"
