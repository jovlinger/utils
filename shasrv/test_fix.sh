#!/bin/bash
# test_fix.sh - Test the --fix mode (repair symlinks after moving them)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_BASE="/tmp/shasrv_test_fix_$$"

cleanup() { rm -rf "$TEST_BASE"; }
trap cleanup EXIT

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

# ---- Setup ----
mkdir -p "$TEST_BASE/source/album1" "$TEST_BASE/source/album2"

echo "content A" > "$TEST_BASE/source/album1/track1.flac"
echo "content B" > "$TEST_BASE/source/album1/track2.flac"
echo "content A" > "$TEST_BASE/source/album2/track1.flac"   # duplicate

STORE="$TEST_BASE/store"

# ---- Ingest ----
python3 "$SCRIPT_DIR/dedup.py" "$TEST_BASE/source" "$STORE" -v
echo ""

# Sanity: symlinks resolve
[ -e "$STORE/files/source/album1/track1.flac" ] || fail "initial symlink missing"
pass "initial ingest"

# ---- Test 1: Move a symlink deeper and fix ----
mkdir -p "$STORE/files/moved/deeper/path"
mv "$STORE/files/source/album1/track1.flac" "$STORE/files/moved/deeper/path/track1.flac"

# Symlink should be broken now (relative path is wrong)
if [ -e "$STORE/files/moved/deeper/path/track1.flac" ]; then
    fail "symlink should be broken after move, but it still resolves"
fi
pass "symlink broken after move"

# Run fix
python3 "$SCRIPT_DIR/dedup.py" --fix "$STORE" -v
echo ""

# Symlink should resolve now
if [ ! -e "$STORE/files/moved/deeper/path/track1.flac" ]; then
    fail "symlink still broken after fix"
fi

# Verify content
actual=$(cat "$STORE/files/moved/deeper/path/track1.flac")
[ "$actual" = "content A" ] || fail "content mismatch after fix (got: $actual)"
pass "fix restored moved symlink"

# ---- Test 2: Move a symlink shallower and fix ----
mv "$STORE/files/source/album1/track2.flac" "$STORE/files/track2.flac"

if [ -e "$STORE/files/track2.flac" ]; then
    fail "symlink should be broken after shallow move"
fi
pass "symlink broken after shallow move"

python3 "$SCRIPT_DIR/dedup.py" --fix "$STORE" -v
echo ""

actual=$(cat "$STORE/files/track2.flac")
[ "$actual" = "content B" ] || fail "content mismatch after shallow fix"
pass "fix restored shallow-moved symlink"

# ---- Test 3: Dryrun does not modify ----
# Break a symlink again
mkdir -p "$STORE/files/drytest"
mv "$STORE/files/track2.flac" "$STORE/files/drytest/track2.flac"

python3 "$SCRIPT_DIR/dedup.py" --fix --dryrun "$STORE" -v
echo ""

# Should still be broken (dryrun)
if [ -e "$STORE/files/drytest/track2.flac" ]; then
    fail "dryrun should not have fixed the symlink"
fi
pass "dryrun did not modify symlinks"

# Actually fix it
python3 "$SCRIPT_DIR/dedup.py" --fix "$STORE" -v
actual=$(cat "$STORE/files/drytest/track2.flac")
[ "$actual" = "content B" ] || fail "final fix content mismatch"
pass "final fix after dryrun"

# ---- Test 4: Already-correct symlinks are untouched ----
output=$(python3 "$SCRIPT_DIR/dedup.py" --fix "$STORE" -v 2>&1)
fixed=$(echo "$output" | grep "Symlinks fixed:" | awk '{print $NF}')
[ "$fixed" = "0" ] || fail "expected 0 fixes on already-correct store, got $fixed"
pass "no-op on already-correct symlinks"

echo ""
echo "All fix tests passed!"
