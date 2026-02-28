#!/bin/sh
# Copy DMZ payload and install scripts to SD card (run on dev machine with SD mounted).
#
# Usage:
#   ./prepare-sd.sh ROOTFS_TAR SD_MOUNT
#
# Example:
#   ./prepare-sd.sh dmz_rootfs.tar /Volumes/boot
#   ./prepare-sd.sh dmz_rootfs.tar /media/mmcblk0p1
#
# Order: 1) export_rootfs.sh 2) prepare-sd.sh 3) Boot Pi 4) dmz-init runs (or run manually)
#
# See plan.md and README.md.

set -e

ROOTFS_TAR="${1:?Usage: $0 ROOTFS_TAR SD_MOUNT}"
SD_MOUNT="${2:?Usage: $0 ROOTFS_TAR SD_MOUNT}"

if [ ! -f "$ROOTFS_TAR" ]; then
    echo "Error: $ROOTFS_TAR not found. Run export_rootfs.sh first."
    exit 1
fi

if [ ! -d "$SD_MOUNT" ]; then
    echo "Error: $SD_MOUNT is not a directory. Mount the SD card first."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

cp "$ROOTFS_TAR" "$SD_MOUNT/"
cp -r "$SCRIPT_DIR" "$SD_MOUNT/install"
chmod +x "$SD_MOUNT/install/run_raw.sh" "$SD_MOUNT/install/export_rootfs.sh" "$SD_MOUNT/install/prepare-sd.sh" 2>/dev/null || true

echo "Copied $ROOTFS_TAR and install/ to $SD_MOUNT"
echo ""
echo "Next: Boot the Pi. dmz-init.start will extract and run, or manually:"
echo "  mkdir -p /tmp/dmz_rootfs && tar -xf $SD_MOUNT/$(basename "$ROOTFS_TAR") -C /tmp/dmz_rootfs"
echo "  $SD_MOUNT/install/run_raw.sh /tmp/dmz_rootfs"
