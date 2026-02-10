#!/bin/bash
# test_mount.sh - Test RO mount detection and automatic remount logic.
#
# Requires: root (uses loopback mount). Skips gracefully if not root.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_BASE="/tmp/shasrv_test_mount_$$"

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1" >&2; exit 1; }

if [ "${EUID:-$(id -u)}" -ne 0 ]; then
    echo "SKIP: test_mount.sh requires root (for mount operations)"
    exit 0
fi

cleanup() {
    umount "$TEST_BASE/mnt" 2>/dev/null || true
    [ -n "${LOOP:-}" ] && losetup -d "$LOOP" 2>/dev/null || true
    rm -rf "$TEST_BASE"
}
trap cleanup EXIT

rm -rf "$TEST_BASE"
mkdir -p "$TEST_BASE/mnt" "$TEST_BASE/source"

# Create a small ext2 image (no journal = simpler), mount RO
IMG="$TEST_BASE/test.img"
dd if=/dev/zero of="$IMG" bs=1M count=10 status=none
mkfs.ext2 -qF "$IMG"

# Pre-populate the image with data/ and files/ directories
TMPMNT="$TEST_BASE/tmpmnt"
mkdir -p "$TMPMNT"
mount -o loop "$IMG" "$TMPMNT"
mkdir -p "$TMPMNT/store/data" "$TMPMNT/store/files"
umount "$TMPMNT"
rmdir "$TMPMNT"

# Mount read-only
mount -o ro,loop "$IMG" "$TEST_BASE/mnt"
LOOP=$(losetup -j "$IMG" | head -1 | cut -d: -f1)

# Verify it's RO
opts=$(findmnt -n -o OPTIONS --target "$TEST_BASE/mnt" | head -1)
echo "$opts" | grep -qw 'ro' || fail "image should be mounted RO"
pass "image mounted RO"

# Create a source file
echo "mount test content" > "$TEST_BASE/source/test.txt"

# Run dedup.sh - it should detect RO, remount RW, dedup, then remount RO
"$SCRIPT_DIR/dedup.sh" "$TEST_BASE/source" "$TEST_BASE/mnt/store" -v
echo ""

# Verify the store was populated
[ -d "$TEST_BASE/mnt/store/data" ] || fail "data/ not found after dedup"
data_count=$(find "$TEST_BASE/mnt/store/data" -type f | wc -l)
[ "$data_count" -ge 1 ] || fail "no data files created"
pass "dedup created data files on previously-RO mount"

# Verify symlink works
[ -e "$TEST_BASE/mnt/store/files/source/test.txt" ] || fail "symlink missing"
actual=$(cat "$TEST_BASE/mnt/store/files/source/test.txt")
[ "$actual" = "mount test content" ] || fail "content mismatch via symlink"
pass "symlink resolves correctly"

# Verify mount is back to RO (the trap should have fired after dedup.sh exited)
opts=$(findmnt -n -o OPTIONS --target "$TEST_BASE/mnt" | head -1)
echo "$opts" | grep -qw 'ro' || fail "mount should be back to RO after dedup.sh"
pass "mount restored to RO after dedup.sh exit"

echo ""
echo "All mount tests passed!"
