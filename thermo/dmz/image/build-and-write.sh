#!/bin/sh
# Build DMZ image and write it to SD card in one command.
#
# Usage:
#   ./build-and-write.sh BLOCK_DEVICE [--output FILE]
#
# Example:
#   ./build-and-write.sh /dev/rdisk4 --output /tmp/dmz-test.img
#
# Requirements:
# - Run from a clean git working tree (no staged/unstaged/untracked changes).
# - Uses sudo for final card write.

set -e

usage() {
    echo "Usage: $0 BLOCK_DEVICE [--output FILE]"
    echo ""
    echo "  BLOCK_DEVICE  SD card block device (e.g. /dev/rdisk4, /dev/sdb)"
    echo "  --output FILE Output image path (default: /tmp/dmz-test.img)"
    exit 1
}

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
OUTPUT="/tmp/dmz-test.img"
DEVICE=""

while [ $# -gt 0 ]; do
    case "$1" in
        --output|-o)
            OUTPUT="${2:-}"
            [ -n "$OUTPUT" ] || usage
            shift 2
            ;;
        --help|-h)
            usage
            ;;
        *)
            if [ -z "$DEVICE" ]; then
                DEVICE="$1"
                shift
            else
                echo "Unexpected arg: $1"
                usage
            fi
            ;;
    esac
done

[ -n "$DEVICE" ] || usage
[ -e "$DEVICE" ] || { echo "Error: device not found: $DEVICE"; exit 1; }

if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
    echo "Error: git working tree is not clean."
    echo "Commit or stash all changes before building/writing the image."
    exit 1
fi

if ! git -C "$REPO_ROOT" rev-parse --verify HEAD >/dev/null 2>&1; then
    echo "Error: no valid git HEAD commit found."
    exit 1
fi

is_device_mounted() {
    mount | grep -q "$DEVICE"
}

unmount_until_clear() {
    case "$(uname)" in
        Darwin)
            retries=15
            while [ "$retries" -gt 0 ]; do
                diskutil unmountDisk force "$DEVICE" >/dev/null 2>&1 || true
                sleep 1
                if ! is_device_mounted; then
                    return 0
                fi
                retries=$((retries - 1))
            done
            return 1
            ;;
        *)
            retries=10
            while [ "$retries" -gt 0 ]; do
                umount "${DEVICE}"* >/dev/null 2>&1 || true
                sleep 1
                if ! is_device_mounted; then
                    return 0
                fi
                retries=$((retries - 1))
            done
            return 1
            ;;
    esac
}

UNMOUNT_PID=""
if is_device_mounted; then
    echo "[preflight] card appears mounted; starting background unmount..."
    (unmount_until_clear) &
    UNMOUNT_PID="$!"
fi

echo "[build] creating image: $OUTPUT"
"$SCRIPT_DIR/create-image.sh" --output "$OUTPUT"

if [ -n "$UNMOUNT_PID" ]; then
    echo "[preflight] waiting for background unmount..."
    if ! wait "$UNMOUNT_PID"; then
        echo "Error: background unmount did not complete successfully."
        exit 1
    fi
fi

if is_device_mounted; then
    echo "Error: device is still mounted: $DEVICE"
    echo "Run: diskutil unmountDisk force $DEVICE"
    exit 1
fi

echo "[write] writing image to card (sudo required)"
sudo "$SCRIPT_DIR/write-to-card.sh" "$OUTPUT" "$DEVICE"
echo "[done] image build+write completed."
