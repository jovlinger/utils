#!/bin/sh
# Compatibility wrapper: deploy the selected hardware backend locally.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO="${REPO_PATH:-$(cd "$SCRIPT_DIR/../../.." && pwd)}"

export ONBOARD_DEPLOY_LOCAL=1
export ONBOARD_DEPLOY_SKIP_GIT_PULL=1
REPO_PATH="$REPO" /bin/sh "$REPO/thermo/onboard/install/deploy.sh" "$@"
