#!/bin/sh
# Create a complete bootable DMZ image for Pi 1B.
# Output: dmz.img suitable for dd onto an SD card.
#
# Usage:
#   ./create-image.sh [--output FILE] [--alpine-version VER] [--size MB]
#
# Prerequisites: Docker, curl/wget, tar, gzip, mkfs.vfat (dosfstools),
#   mcopy/mmd (mtools) or mount (Linux/macOS with loop device).
#
# See ../plan.md and README.md.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DMZ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT="${SCRIPT_DIR}/dmz.img"
ALPINE_VERSION="3.23.3"
IMAGE_SIZE_MB=256
ALPINE_MIRROR="https://dl-cdn.alpinelinux.org/alpine"
ALPINE_BRANCH="v3.23"

while [ $# -gt 0 ]; do
    case "$1" in
        --output|-o) OUTPUT="$2"; shift 2 ;;
        --alpine-version) ALPINE_VERSION="$2"; shift 2 ;;
        --size) IMAGE_SIZE_MB="$2"; shift 2 ;;
        --help|-h)
            echo "Usage: $0 [--output FILE] [--alpine-version VER] [--size MB]"
            echo "  --output FILE       Output image path (default: dmz.img in script dir)"
            echo "  --alpine-version V  Alpine version (default: 3.23.3)"
            echo "  --size MB            Image size in MB (default: 256)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "==> Creating DMZ image for Pi 1B"
echo "    Output: $OUTPUT"
echo "    Alpine: $ALPINE_VERSION"
echo "    Size: ${IMAGE_SIZE_MB}MB"
echo ""

# 1. Build Docker image
echo "[1/8] Building Docker image (ARMv6)..."
(cd "$DMZ_ROOT" && docker buildx build --platform linux/arm/v6 -t jovlinger/thermo/dmz --load .)

# 2. Export rootfs
echo "[2/8] Exporting rootfs..."
ROOTFS_TAR="$WORKDIR/dmz_rootfs.tar"
cid=$(docker create jovlinger/thermo/dmz)
trap 'docker rm -f "$cid" 2>/dev/null || true; rm -rf "$WORKDIR"' EXIT
docker export "$cid" > "$ROOTFS_TAR"
docker rm -f "$cid" 2>/dev/null || true
trap 'rm -rf "$WORKDIR"' EXIT

# 3. Download Alpine RPi armhf tarball
echo "[3/8] Downloading Alpine RPi armhf $ALPINE_VERSION..."
ALPINE_TAR="alpine-rpi-${ALPINE_VERSION}-armhf.tar.gz"
ALPINE_URL="${ALPINE_MIRROR}/latest-stable/releases/armhf/${ALPINE_TAR}"
ALPINE_SHA_URL="${ALPINE_MIRROR}/latest-stable/releases/armhf/${ALPINE_TAR}.sha256"

if command -v curl >/dev/null 2>&1; then
    curl -sL -o "$WORKDIR/$ALPINE_TAR" "$ALPINE_URL"
    curl -sL -o "$WORKDIR/$ALPINE_TAR.sha256" "$ALPINE_SHA_URL"
else
    wget -q -O "$WORKDIR/$ALPINE_TAR" "$ALPINE_URL"
    wget -q -O "$WORKDIR/$ALPINE_TAR.sha256" "$ALPINE_SHA_URL"
fi

(cd "$WORKDIR" && sha256sum -c "$ALPINE_TAR.sha256" 2>/dev/null || shasum -a 256 -c "$ALPINE_TAR.sha256" 2>/dev/null || true)

# 4. Extract Alpine tarball
echo "[4/8] Extracting Alpine base..."
ALPINE_EXTRACT="$WORKDIR/alpine_extract"
mkdir -p "$ALPINE_EXTRACT"
tar -xzf "$WORKDIR/$ALPINE_TAR" -C "$ALPINE_EXTRACT"

# 5. Pre-download apk packages (armhf) for offline boot
echo "[5/8] Fetching apk packages (bubblewrap, haveged, chrony, iptables)..."
APKS_DIR="$WORKDIR/apks"
mkdir -p "$APKS_DIR"
docker run --rm --platform linux/arm/v6 \
    -v "$APKS_DIR:/out" \
    alpine:${ALPINE_VERSION} \
    sh -c "apk update && apk fetch -o /out bubblewrap haveged chrony iptables"

# Add to Alpine's apks/armhf/ (base tarball already has this structure)
mkdir -p "$ALPINE_EXTRACT/apks/armhf"
cp "$APKS_DIR"/*.apk "$ALPINE_EXTRACT/apks/armhf/" 2>/dev/null || true

# 6. Build apkovl
echo "[6/8] Building apkovl..."
APKOVL_DIR="$WORKDIR/apkovl"
mkdir -p "$APKOVL_DIR/etc/local.d"
mkdir -p "$APKOVL_DIR/etc/apk"

cp "$DMZ_ROOT/install/dmz-init.start" "$APKOVL_DIR/etc/local.d/"
chmod +x "$APKOVL_DIR/etc/local.d/dmz-init.start"

# etc/apk/world: packages to install at boot
printf '%s\n' "bubblewrap" "haveged" "chrony" "iptables" > "$APKOVL_DIR/etc/apk/world"

# etc/apk/repositories: use local apks on boot partition for offline
echo "/media/mmcblk0p1/apks" > "$APKOVL_DIR/etc/apk/repositories"

# etc/hostname for consistent apkovl naming
echo "dmz" > "$APKOVL_DIR/etc/hostname"

(cd "$APKOVL_DIR" && tar -czf "$WORKDIR/dmz.apkovl.tar.gz" etc/)

# 7. Create FAT32 image and populate
echo "[7/8] Creating FAT32 image..."

IMG_FILE="$WORKDIR/dmz.img"
dd if=/dev/zero of="$IMG_FILE" bs=1M count="$IMAGE_SIZE_MB" 2>/dev/null

if ! command -v mkfs.vfat >/dev/null 2>&1; then
    echo "Error: mkfs.vfat not found. Install dosfstools (Linux) or use macOS with diskutil."
    exit 1
fi

# Avoid volume label "boot" per Alpine wiki (firmware bug)
mkfs.vfat -n PIBOOT -F 32 "$IMG_FILE" 2>/dev/null || mkfs.vfat -F 32 "$IMG_FILE"

# Copy files using mtools (no root required)
if command -v mcopy >/dev/null 2>&1 && command -v mmd >/dev/null 2>&1; then
    echo "    Using mtools..."
    for x in "$ALPINE_EXTRACT"/*; do
        [ -e "$x" ] || continue
        mcopy -i "$IMG_FILE" -s "$x" "::$(basename "$x")"
    done
    mcopy -i "$IMG_FILE" "$ROOTFS_TAR" ::dmz_rootfs.tar
    mmd -i "$IMG_FILE" ::install
    for f in "$DMZ_ROOT/install"/*; do
        [ -e "$f" ] || continue
        mcopy -i "$IMG_FILE" "$f" "::install/$(basename "$f")"
    done
    mcopy -i "$IMG_FILE" "$WORKDIR/dmz.apkovl.tar.gz" ::dmz.apkovl.tar.gz
else
    echo "    Using mount (requires sudo)..."
    MOUNT_POINT="$WORKDIR/mnt"
    mkdir -p "$MOUNT_POINT"
    LOOP_DEV=""

    case "$(uname)" in
        Linux)
            LOOP_DEV=$(sudo losetup -f --show "$IMG_FILE")
            sudo mount -t vfat "$LOOP_DEV" "$MOUNT_POINT"
            ;;
        Darwin)
            LOOP_DEV=$(hdiutil attach -imagekey diskimage-class=CRawDiskImage -nomount "$IMG_FILE" 2>/dev/null | head -1 | awk '{print $1}')
            [ -n "$LOOP_DEV" ] && sudo mount -t msdos "$LOOP_DEV" "$MOUNT_POINT"
            ;;
        *)
            echo "Error: Install mtools (brew install mtools) or run on Linux."
            exit 1
            ;;
    esac

    if [ -z "$LOOP_DEV" ]; then
        echo "Error: Could not attach image. Install mtools: brew install mtools dosfstools"
        exit 1
    fi

    cp -a "$ALPINE_EXTRACT"/* "$MOUNT_POINT/"
    cp "$ROOTFS_TAR" "$MOUNT_POINT/dmz_rootfs.tar"
    cp -r "$DMZ_ROOT/install" "$MOUNT_POINT/"
    cp "$WORKDIR/dmz.apkovl.tar.gz" "$MOUNT_POINT/"
    chmod +x "$MOUNT_POINT/install/run_raw.sh" 2>/dev/null || true

    case "$(uname)" in
        Linux) sudo umount "$MOUNT_POINT" && sudo losetup -d "$LOOP_DEV" 2>/dev/null || true ;;
        Darwin) sudo umount "$MOUNT_POINT" && hdiutil detach "$LOOP_DEV" 2>/dev/null || true ;;
    esac
fi

# 8. Move to output
echo "[8/8] Finalizing..."
mkdir -p "$(dirname "$OUTPUT")"
mv "$IMG_FILE" "$OUTPUT"

# Checksum
if command -v sha256sum >/dev/null 2>&1; then
    SHA=$(sha256sum "$OUTPUT" | awk '{print $1}')
else
    SHA=$(shasum -a 256 "$OUTPUT" | awk '{print $1}')
fi

echo ""
echo "==> Done. Image: $OUTPUT"
echo "    SHA256: $SHA"
echo ""
echo "Next: Write to SD card with:"
echo "  ./write-to-card.sh $OUTPUT /dev/sdX"
echo ""
echo "Then boot the Pi 1B; dmz-init runs automatically."
