#!/bin/bash
# test_ingest_root_gate.sh - Verify ingest.sh does not require running as root.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

if [ "${EUID:-$(id -u)}" -eq 0 ]; then
    echo "SKIP: running as root; non-root gate check is not applicable"
    exit 0
fi

grep -qE '\[ "\$\{EUID:-\$\(id -u\)\}" -ne 0 \]' "$SCRIPT_DIR/ingest.sh" &&
    fail "ingest.sh should not require root (remove EUID gate)"

grep -q 'err "run with sudo"' "$SCRIPT_DIR/ingest.sh" &&
    fail "ingest.sh should not tell users to run the whole script with sudo"

pass "ingest.sh has no whole-script root/sudo requirement"

echo ""
echo "Root-gate test passed!"
