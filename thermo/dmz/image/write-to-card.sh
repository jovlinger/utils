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

# Linux: block device (-b). macOS: whole disk can be -b, -c, or a directory; accept if writable.
if [ ! -e "$DEVICE" ]; then
    echo "Error: $DEVICE does not exist."
    echo ""
    echo "To find the SD card device:"
    echo "  macOS:   Insert the card, then run:  diskutil list"
    echo "           Use the whole disk (e.g. /dev/disk4), not a partition (disk4s1)."
    echo "           Unmount (keeps device for raw write):  diskutil unmountDisk /dev/disk4"
    echo "           Then use:       sudo $0 $IMAGE /dev/rdisk4"
    echo "  Linux:   lsblk  or  ls /dev/sd*  (use /dev/sdb etc., not sdb1)"
    exit 1
fi
if [ -d "$DEVICE" ]; then
    echo "Error: $DEVICE is a directory (use the whole disk, e.g. /dev/rdisk4 not a partition)."
    exit 1
fi
if [ ! -b "$DEVICE" ] && [ ! -c "$DEVICE" ]; then
    # macOS sometimes exposes disks in a way that isn't -b/-c; allow if readable and writable
    if [ ! -r "$DEVICE" ] || [ ! -w "$DEVICE" ]; then
        echo "Error: $DEVICE is not a block/character device and is not read-write."
        echo "Try /dev/rdisk4 (macOS) or run with sudo."
        exit 1
    fi
fi

# Safety: refuse obvious system disks
case "$DEVICE" in
    /dev/sda|/dev/sda*|/dev/nvme*|/dev/vda|/dev/vda*)
        echo "Error: Refusing to write to $DEVICE (likely system disk)."
        echo "Use the SD card device (e.g. /dev/sdb, /dev/mmcblk0)."
        exit 1
        ;;
esac

# Check if device or its partitions are mounted
if mount | grep -q "$DEVICE"; then
    case "$(uname)" in
        Darwin)
            printf "Unmount disk now? (y/n): "
            read -r unmount_ok
            if [ "$unmount_ok" = "y" ] || [ "$unmount_ok" = "Y" ]; then
                # Try normal unmount, then force in a loop (mds_stores may dissent; retry until it gives up)
                if ! diskutil unmountDisk "$DEVICE" 2>/dev/null; then
                    retries=5
                    while [ "$retries" -gt 0 ]; do
                        echo "Unmount busy; forcing in 3s... $retries retries left"
                        sleep 3
                        diskutil unmountDisk force "$DEVICE" 2>/dev/null && break
                        retries=$((retries - 1))
                    done
                    if mount | grep -q "$DEVICE"; then
                        echo "Force unmount failed. Run: diskutil unmountDisk force $DEVICE"
                        exit 1
                    fi
                fi
            else
                echo "Aborted. Unmount first: diskutil unmountDisk $DEVICE"
                exit 1
            fi
            ;;
        *)
            echo "Error: $DEVICE or its partitions appear to be mounted."
            echo "Unmount first: umount ${DEVICE}*"
            exit 1
            ;;
    esac
fi

IMAGE_SIZE=$(stat -f%z "$IMAGE" 2>/dev/null || stat -c%s "$IMAGE" 2>/dev/null)
DEVICE_SIZE=$(blockdev --getsize64 "$DEVICE" 2>/dev/null || true)
if [ -n "$DEVICE_SIZE" ] && [ -n "$IMAGE_SIZE" ] && [ "$IMAGE_SIZE" -gt "$DEVICE_SIZE" ]; then
    echo "Error: Image size $IMAGE_SIZE is larger than device size $DEVICE_SIZE."
    exit 1
fi

echo "Writing $IMAGE to $DEVICE..."
dd if="$IMAGE" of="$DEVICE" bs=4M status=progress conv=fsync

echo ""
echo "Done. Remove the SD card and boot the Pi 1B."
