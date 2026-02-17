#!/bin/bash
# test_ingest_root_gate.sh - Verify ingest.sh enforces sudo/root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_BASE="/tmp/shadup_test_ingest_root_$$"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

cleanup() { rm -rf "$TEST_BASE"; }
trap cleanup EXIT

mkdir -p "$TEST_BASE"
out="$TEST_BASE/out.txt"

set +e
"$SCRIPT_DIR/ingest.sh" "$TEST_BASE/does-not-matter" >"$out" 2>&1
rc=$?
set -e

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    echo "SKIP: running as root; root-gate check is not applicable"
    exit 0
fi

[ "$rc" -ne 0 ] || fail "expected non-zero exit when not root"
grep -q "run with sudo" "$out" || fail "expected 'run with sudo' error"
pass "ingest.sh rejects non-root execution"

echo ""
echo "Root-gate test passed!"
