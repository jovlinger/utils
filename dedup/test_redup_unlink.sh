#!/bin/bash
# test_redup_unlink.sh - --unlink removes only exported data blobs

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UTILS_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TEST_BASE="/tmp/shasrv_test_redup_unlink_$$"

if [ ! -f "$SCRIPT_DIR/env/bin/activate" ] && [ ! -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  echo "No venv at $SCRIPT_DIR/env or $SCRIPT_DIR/.venv." >&2
  echo "Run: $UTILS_ROOT/create_pipenv.sh dedup" >&2
  exit 1
fi
if [ -f "$SCRIPT_DIR/.venv/bin/activate" ]; then
  . "$SCRIPT_DIR/.venv/bin/activate"
else
  . "$SCRIPT_DIR/env/bin/activate"
fi

cleanup() { rm -rf "$TEST_BASE"; }
trap cleanup EXIT

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

mkdir -p "$TEST_BASE/source"
echo "keep-me-orphan" > "$TEST_BASE/source/orphan.txt"
echo "export-me" > "$TEST_BASE/source/keep.txt"
echo "export-dup" > "$TEST_BASE/source/a.txt"
echo "export-dup" > "$TEST_BASE/source/b.txt"

STORE="$TEST_BASE/store"
DEST="$TEST_BASE/out"

python "$SCRIPT_DIR/dedup.py" "$TEST_BASE/source" "$STORE" -v
echo ""

ORPHAN_LINK="$STORE/files/source/orphan.txt"
KEEP_LINK="$STORE/files/source/keep.txt"
A_LINK="$STORE/files/source/a.txt"
B_LINK="$STORE/files/source/b.txt"

ORPHAN_DATA=$(realpath "$ORPHAN_LINK")
KEEP_DATA=$(realpath "$KEEP_LINK")
A_DATA=$(realpath "$A_LINK")
[ "$A_DATA" = "$(realpath "$B_LINK")" ] || fail "a.txt and b.txt should share a blob"

# Delete orphan symlink before export; its blob must survive --unlink.
rm -f "$ORPHAN_LINK"
[ -f "$ORPHAN_DATA" ] || fail "orphan data missing after symlink delete"
pass "orphan symlink removed; data retained"

"$SCRIPT_DIR/redup.sh" --unlink "$STORE" "$DEST"
echo ""

[ -f "$DEST/source/keep.txt" ] || fail "keep.txt missing from export"
[ -f "$DEST/source/a.txt" ] || fail "a.txt missing from export"
[ -f "$DEST/source/b.txt" ] || fail "b.txt missing from export"
[ ! -e "$DEST/source/orphan.txt" ] || fail "orphan should not appear in export"
pass "export tree contents"

[ -f "$ORPHAN_DATA" ] || fail "orphan data was unlinked but was not exported"
pass "orphan data still in data/"

[ ! -e "$KEEP_DATA" ] || fail "exported keep blob still present in data/"
[ ! -e "$A_DATA" ] || fail "exported shared blob still present in data/"
pass "exported data blobs removed"

[ ! -e "$KEEP_LINK" ] || fail "exported keep symlink still in files/"
[ ! -e "$A_LINK" ] || fail "exported a.txt symlink still in files/"
[ ! -e "$B_LINK" ] || fail "exported b.txt symlink still in files/"
pass "exported files/ entries removed"

actual=$(cat "$DEST/source/keep.txt")
[ "$actual" = "export-me" ] || fail "keep.txt content mismatch"
pass "exported content intact"

inode_of() {
  if stat -f%i "$1" >/dev/null 2>&1; then
    stat -f%i "$1"
  else
    stat -c%i "$1"
  fi
}
inode_a=$(inode_of "$DEST/source/a.txt")
inode_b=$(inode_of "$DEST/source/b.txt")
inode_keep=$(inode_of "$DEST/source/keep.txt")
[ "$inode_a" = "$inode_b" ] || fail "a.txt and b.txt should share inode (got $inode_a vs $inode_b)"
[ "$inode_a" != "$inode_keep" ] || fail "keep.txt should not share inode with a/b"
pass "shared-blob exports share inode"

echo ""
echo "All redup --unlink tests passed!"
