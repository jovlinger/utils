#!/usr/bin/env bash
# Post-flash: run a named suite via Test actor (mode=suite).
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
SUITE="${1:-smoke}"
exec "$DIR/run_test.sh" --mode suite "$SUITE"
