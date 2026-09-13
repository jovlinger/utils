#!/usr/bin/env bash
# Timeboxed shadup tests. Usage:
#   ./run-tests.sh              # full suite, ≤60s wall
#   ./run-tests.sh refresh      # _meta / _tags circular mirrors only
#   ./run-tests.sh min          # unit smoke for shared meta links
#   ./run-tests.sh <pytest args...>
set -euo pipefail
cd "$(dirname "$0")"
PY="${PWD}/.venv/bin/python"
WALL="${SHADUP_TEST_WALL:-60}"

args=()
case "${1:-}" in
  ""|all|full)
    shift || true
    args=(tests)
    ;;
  refresh)
    shift
    args=(tests/test_refresh_extracted_tags.py)
    ;;
  min)
    shift
    args=(tests/test_refresh_extracted_tags.py::test_shared_meta_across_two_tag_buckets)
    ;;
  *)
    args=("$@")
    set --
    ;;
esac
# remaining "$@" appended when case used shift
args+=("$@")

exec timeout --foreground "${WALL}s" "$PY" -m pytest "${args[@]}"
