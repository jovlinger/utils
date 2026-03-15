#!/bin/sh
# Write a DMZ image to an SD card.
#
# Usage:
#   ./write-to-card.sh IMAGE_FILE /dev/sdX
#
# Example:
#   ./write-to-card.sh dmz.img /dev/sdb
#
# WARNING: This will overwrite the entire device. Ensure you specify the
# correct SD card device (e.g. /dev/sdb, /dev/mmcblk0).
#
# See README.md.

set -e

usage() {
    echo "Usage: $0 IMAGE_FILE BLOCK_DEVICE"
    echo ""
    echo "  IMAGE_FILE    Path to dmz.img (from create-image.sh)"
    echo "  BLOCK_DEVICE  SD card device (e.g. /dev/sdb, /dev/mmcblk0)"
    echo ""
    echo "Example: $0 dmz.img /dev/sdb"
    exit 1
}

IMAGE="${1:?}"
DEVICE="${2:?}"

[ "$1" = "--help" ] || [ "$1" = "-h" ] && usage

if [ ! -f "$IMAGE" ]; then
    echo "Error: Image file not found: $IMAGE"
    exit 1
fi

if [ ! -b "$DEVICE" ]; then
    echo "Error: $DEVICE is not a block device."
    echo "Specify the SD card device (e.g. /dev/sdb)."
    exit 1
fi

# Safety: refuse obvious system disks
case "$DEVICE" in
    /dev/sda|/dev/sda*|/dev/nvme*|/dev/vda|/dev/vda*)
        echo "Error: Refusing to write to $DEVICE (likely system disk)."
        echo "Use the SD card device (e.g. /dev/sdb, /dev/mmcblk0)."
        exit 1
        ;;
esac

# Check if device has mounted partitions
if mount | grep -q "^$DEVICE"; then
    echo "Error: $DEVICE or its partitions appear to be mounted."
    echo "Unmount first: umount ${DEVICE}*"
    exit 1
fi

IMAGE_SIZE=$(stat -f%z "$IMAGE" 2>/dev/null || stat -c%s "$IMAGE" 2>/dev/null)
DEVICE_SIZE=$(blockdev --getsize64 "$DEVICE" 2>/dev/null || true)
if [ -n "$DEVICE_SIZE" ] && [ -n "$IMAGE_SIZE" ] && [ "$IMAGE_SIZE" -gt "$DEVICE_SIZE" ]; then
    echo "Error: Image ($IMAGE_SIZE bytes) is larger than device ($DEVICE_SIZE bytes)."
    exit 1
fi

echo "About to overwrite $DEVICE with $IMAGE"
echo "All data on $DEVICE will be destroyed."
echo ""
printf "Type YES to proceed: "
read -r confirm
if [ "$confirm" != "YES" ]; then
    echo "Aborted."
    exit 1
fi

echo ""
echo "Writing..."
dd if="$IMAGE" of="$DEVICE" bs=4M status=progress conv=fsync

echo ""
echo "Done. Remove the SD card and boot the Pi 1B."
