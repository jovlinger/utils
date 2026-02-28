#!/bin/sh
# Export a Docker image to a rootfs tarball for "raw" execution (bwrap/chroot) on Pi 1B.
#
# Usage:
#   ./export_rootfs.sh [IMAGE] [OUTPUT]
#
# Examples:
#   ./export_rootfs.sh                          # uses jovlinger/thermo/dmz, writes dmz_rootfs.tar
#   ./export_rootfs.sh jovlinger/thermo/dmz     # same
#   ./export_rootfs.sh my/img ./payload.tar     # custom image and output path
#
# For Pi 1B (ARMv6), build the image first with:
#   docker buildx build --platform linux/arm/v6 -t jovlinger/thermo/dmz .
#
# See plan.md and README.md. To run the rootfs without Docker, use run_raw.sh.

set -e

IMAGE="${1:-jovlinger/thermo/dmz}"
OUTPUT="${2:-dmz_rootfs.tar}"

cid=$(docker create "$IMAGE")
trap 'docker rm -f "$cid" 2>/dev/null || true' EXIT
docker export "$cid" > "$OUTPUT"
docker rm -f "$cid" 2>/dev/null || true
trap - EXIT

echo "Exported to $OUTPUT"
echo ""
echo "On the Pi 1B:"
echo "  1. Copy $OUTPUT to SD (e.g. /media/mmcblk0p1/)"
echo "  2. mkdir -p /tmp/dmz_rootfs && tar -xf $OUTPUT -C /tmp/dmz_rootfs"
echo "  3. ./install/run_raw.sh /tmp/dmz_rootfs"
echo ""
echo "Or use run_raw.sh --help for options."
