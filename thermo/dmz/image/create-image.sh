#!/bin/sh
# Create a complete bootable DMZ image for Pi 1B.
# Output: dmz.img suitable for dd onto an SD card.
#
# Usage:
#   ./create-image.sh [--output FILE] [--alpine-version VER] [--size MB]
#
# Prerequisites: Docker, curl/wget, tar, gzip, mkfs.vfat (dosfstools),
#   mcopy/mmd (mtools) or mount (Linux/macOS with loop device).
#   macOS: brew install dosfstools mtools
#
# See ../plan.md and README.md.

set -e

ts() { echo "[$(date '+%H:%M:%S')] $*"; }

# Optional verbose shell tracing for long builds:
#   CREATE_IMAGE_TRACE=1 ./create-image.sh ...
if [ "${CREATE_IMAGE_TRACE:-0}" = "1" ]; then
    set -x
fi

# Homebrew installs dosfstools to sbin; ensure it's on PATH (macOS)
case "$(uname)" in
    Darwin)
        for d in /opt/homebrew/sbin /usr/local/sbin; do
            [ -d "$d" ] && PATH="$d:$PATH"
        done
        ;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DMZ_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$DMZ_ROOT/../.." && pwd)"
BIN_ROOT="$(cd "$DMZ_ROOT/../../.." && pwd)/bin"
RUN_WITH_STDOUT_LOGGED_SRC="$BIN_ROOT/run-with-stdout-logged.py"
OUTPUT="/tmp/dmz.img"
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

ts "==> Creating DMZ image for Pi 1B"
echo "    Output: $OUTPUT"
echo "    Alpine: $ALPINE_VERSION"
echo "    Size: ${IMAGE_SIZE_MB}MB"
echo ""

# 1. Build Docker image
ts "[1/8] Building Docker image (ARMv6)..."
if [ ! -f "$RUN_WITH_STDOUT_LOGGED_SRC" ]; then
    echo "Error: missing external runner script: $RUN_WITH_STDOUT_LOGGED_SRC"
    echo "Expected source is ../bin/run-with-stdout-logged.py relative to repo checkout root."
    exit 1
fi
BUILD_CTX="$WORKDIR/dmz_build_ctx"
mkdir -p "$BUILD_CTX"
cp -a "$DMZ_ROOT"/. "$BUILD_CTX"/
cp "$RUN_WITH_STDOUT_LOGGED_SRC" "$BUILD_CTX/run-with-stdout-logged.py"
(cd "$BUILD_CTX" && docker buildx build --progress=plain --platform linux/arm/v6 -t jovlinger/thermo/dmz --load .)
ts "[1/8] Docker build done."

# 2. Export rootfs
ts "[2/8] Exporting rootfs..."
ROOTFS_TAR="$WORKDIR/dmz_rootfs.tar"
cid=$(docker create jovlinger/thermo/dmz)
trap 'docker rm -f "$cid" 2>/dev/null || true; rm -rf "$WORKDIR"' EXIT
docker export "$cid" > "$ROOTFS_TAR"
docker rm -f "$cid" 2>/dev/null || true
trap 'rm -rf "$WORKDIR"' EXIT
ts "[2/8] Rootfs export done."

# 3. Download Alpine RPi armhf tarball
ts "[3/8] Downloading Alpine RPi armhf $ALPINE_VERSION..."
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
ts "[3/8] Alpine tarball download done."

# 4. Extract Alpine tarball
ts "[4/8] Extracting Alpine base..."
ALPINE_EXTRACT="$WORKDIR/alpine_extract"
mkdir -p "$ALPINE_EXTRACT"
tar -xzf "$WORKDIR/$ALPINE_TAR" -C "$ALPINE_EXTRACT"
# Do NOT add apkovl= to cmdline: with apkovl=FILE the init checks [ -f "FILE" ] in current dir and fails (file is on boot media). Leave unset so init uses /tmp/apkovls (full path from nlplug-findfs). We put alpine.apkovl.tar.gz and dmz.apkovl.tar.gz on the card; nlplug-findfs finds one and writes its full path.
ts "[4/8] Alpine extract done."

# 5. Pre-download apk packages (armhf) + APKINDEX for offline boot
# Use main + community dirs so apk can find indexes and install at boot.
ts "[5/8] Fetching apk packages (bubblewrap, haveged, iptables, dhcpcd + deps)..."
APKS_MAIN="$WORKDIR/apks_main"
APKS_COMMUNITY="$WORKDIR/apks_community"
mkdir -p "$APKS_MAIN/armhf" "$APKS_COMMUNITY/armhf"

# iptables needs libmnl, libnftnl, libxtables; clock uses busybox ntpd (no chrony)
docker run --rm --platform linux/arm/v6 \
    -v "$APKS_MAIN/armhf:/out" \
    alpine:${ALPINE_VERSION} \
    sh -c "echo 'https://dl-cdn.alpinelinux.org/alpine/${ALPINE_BRANCH}/main' > /etc/apk/repositories && apk update && apk fetch -o /out iptables dhcpcd libmnl libnftnl libxtables"

docker run --rm --platform linux/arm/v6 \
    -v "$APKS_COMMUNITY/armhf:/out" \
    alpine:${ALPINE_VERSION} \
    sh -c "printf '%s\n' 'https://dl-cdn.alpinelinux.org/alpine/${ALPINE_BRANCH}/main' 'https://dl-cdn.alpinelinux.org/alpine/${ALPINE_BRANCH}/community' > /etc/apk/repositories && apk update && apk fetch -o /out bubblewrap haveged"

# Download APKINDEX so apk can install from local at boot
if command -v curl >/dev/null 2>&1; then
    curl -sL "${ALPINE_MIRROR}/${ALPINE_BRANCH}/main/armhf/APKINDEX.tar.gz" -o "$APKS_MAIN/armhf/APKINDEX.tar.gz"
    curl -sL "${ALPINE_MIRROR}/${ALPINE_BRANCH}/community/armhf/APKINDEX.tar.gz" -o "$APKS_COMMUNITY/armhf/APKINDEX.tar.gz"
else
    wget -q -O "$APKS_MAIN/armhf/APKINDEX.tar.gz" "${ALPINE_MIRROR}/${ALPINE_BRANCH}/main/armhf/APKINDEX.tar.gz"
    wget -q -O "$APKS_COMMUNITY/armhf/APKINDEX.tar.gz" "${ALPINE_MIRROR}/${ALPINE_BRANCH}/community/armhf/APKINDEX.tar.gz"
fi

mkdir -p "$ALPINE_EXTRACT/apks/main/armhf" "$ALPINE_EXTRACT/apks/community/armhf"
cp "$APKS_MAIN/armhf"/* "$ALPINE_EXTRACT/apks/main/armhf/" 2>/dev/null || true
cp "$APKS_COMMUNITY/armhf"/* "$ALPINE_EXTRACT/apks/community/armhf/" 2>/dev/null || true
ts "[5/8] Apk fetch done."

# 6. Build apkovl (overlay): extract .apk payloads into overlay so no apk at boot is needed
ts "[6/8] Building apkovl (extract bwrap, haveged, iptables, dhcpcd into overlay)..."
APKOVL_DIR="$WORKDIR/apkovl"
mkdir -p "$APKOVL_DIR"
# Each .apk is a tarball (no data.tar.gz); extract payload in container, exclude metadata
docker run --rm --platform linux/arm/v6 \
    -v "$APKOVL_DIR:/overlay" \
    -v "$APKS_MAIN/armhf:/pkg_main:ro" \
    -v "$APKS_COMMUNITY/armhf:/pkg_community:ro" \
    alpine:${ALPINE_VERSION} \
    sh -c "for f in /pkg_main/*.apk /pkg_community/*.apk; do [ -f \"\$f\" ] && tar -xzf \"\$f\" -C /overlay; done"

mkdir -p "$APKOVL_DIR/etc/local.d" "$APKOVL_DIR/etc/runlevels/default" "$APKOVL_DIR/etc/apk"
cp "$DMZ_ROOT/install/dmz-init.start" "$APKOVL_DIR/etc/local.d/"
chmod +x "$APKOVL_DIR/etc/local.d/dmz-init.start"
# local service is not in default runlevel by default; enable so local.d/*.start run
ln -s ../../init.d/local "$APKOVL_DIR/etc/runlevels/default/local"
# No repos/world in overlay so boot never runs apk (no APKINDEX.tar.gz warnings)
: > "$APKOVL_DIR/etc/apk/repositories"
: > "$APKOVL_DIR/etc/apk/world"
echo "dmz" > "$APKOVL_DIR/etc/hostname"

# Build ID: SHASUM(create-image.sh + install/*)[:8].upper()
if command -v sha256sum >/dev/null 2>&1; then
    BUILD_HASH=$( ( cat "$SCRIPT_DIR/create-image.sh"; find "$DMZ_ROOT/install" -type f -exec cat {} \; 2>/dev/null ) | sha256sum | awk '{print $1}')
else
    BUILD_HASH=$( ( cat "$SCRIPT_DIR/create-image.sh"; find "$DMZ_ROOT/install" -type f -exec cat {} \; 2>/dev/null ) | shasum -a 256 | awk '{print $1}')
fi
BUILD_ID=$(echo "$BUILD_HASH" | cut -c1-8 | tr '[:lower:]' '[:upper:]')
BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
BUILDINFO_LINE="${BUILD_ID} $BUILD_DATE"
GIT_SHA=$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo "unknown")
REPO_NAME=$(basename "$REPO_ROOT")
echo "$BUILDINFO_LINE" > "$WORKDIR/buildinfo.txt"
echo "repo=$REPO_NAME" >> "$WORKDIR/buildinfo.txt"
echo "git_sha=$GIT_SHA" >> "$WORKDIR/buildinfo.txt"
mkdir -p "$APKOVL_DIR/root" "$APKOVL_DIR/root/.ssh"
echo "DMZ image: $BUILDINFO_LINE" > "$APKOVL_DIR/root/README"
echo "Repo: $REPO_NAME" >> "$APKOVL_DIR/root/README"
echo "Git SHA: $GIT_SHA" >> "$APKOVL_DIR/root/README"
echo "cat /root/README for build ID. dmz-init: /etc/local.d/dmz-init.start" >> "$APKOVL_DIR/root/README"
cp "$DMZ_ROOT/install/root-network-sshd.sh" "$APKOVL_DIR/root/network-and-sshd.sh"
chmod +x "$APKOVL_DIR/root/network-and-sshd.sh"
ID_RSA_PUB="${HOME:-/root}/.ssh/id_rsa.pub"
if [ ! -s "$ID_RSA_PUB" ]; then
    echo "Error: ~/.ssh/id_rsa.pub not found or empty."
    exit 1
fi
cp "$ID_RSA_PUB" "$APKOVL_DIR/root/.ssh/authorized_keys"
chmod 600 "$APKOVL_DIR/root/.ssh/authorized_keys"
cp "$DMZ_ROOT/install/network.conf" "$APKOVL_DIR/root/network.conf"
echo "DMZ $BUILDINFO_LINE" > "$APKOVL_DIR/etc/issue"

(cd "$APKOVL_DIR" && tar -czf "$WORKDIR/dmz.apkovl.tar.gz" .)
ts "[6/8] Apkovl done."

# 7. Create FAT32 image and populate
ts "[7/8] Creating FAT32 image..."

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
    n=0
    for x in "$ALPINE_EXTRACT"/*; do
        [ -e "$x" ] || continue
        n=$((n+1))
        ts "    mcopy $n: $(basename "$x")..."
        mcopy -i "$IMG_FILE" -s "$x" "::$(basename "$x")"
    done
    mcopy -i "$IMG_FILE" "$ROOTFS_TAR" ::dmz_rootfs.tar
    mmd -i "$IMG_FILE" ::install
    mmd -i "$IMG_FILE" ::debug
    for f in "$DMZ_ROOT/install"/*; do
        [ -e "$f" ] || continue
        mcopy -i "$IMG_FILE" "$f" "::install/$(basename "$f")"
    done
    mcopy -i "$IMG_FILE" "$WORKDIR/buildinfo.txt" ::install/buildinfo.txt
    mcopy -i "$IMG_FILE" "$WORKDIR/buildinfo.txt" ::BUILD.txt
    mcopy -i "$IMG_FILE" "$DMZ_ROOT/install/CARD-README.txt" ::README.txt
    mcopy -i "$IMG_FILE" "$WORKDIR/dmz.apkovl.tar.gz" ::dmz.apkovl.tar.gz
    mcopy -i "$IMG_FILE" "$WORKDIR/dmz.apkovl.tar.gz" ::alpine.apkovl.tar.gz
    ts "[7/8] mtools copy done."
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
    cp "$WORKDIR/buildinfo.txt" "$MOUNT_POINT/install/"
    cp "$WORKDIR/buildinfo.txt" "$MOUNT_POINT/BUILD.txt"
    cp "$DMZ_ROOT/install/CARD-README.txt" "$MOUNT_POINT/README.txt"
    cp "$WORKDIR/dmz.apkovl.tar.gz" "$MOUNT_POINT/"
    cp "$WORKDIR/dmz.apkovl.tar.gz" "$MOUNT_POINT/alpine.apkovl.tar.gz"
    mkdir -p "$MOUNT_POINT/debug"
    chmod +x "$MOUNT_POINT/install/run_raw.sh" 2>/dev/null || true

    case "$(uname)" in
        Linux) sudo umount "$MOUNT_POINT" && sudo losetup -d "$LOOP_DEV" 2>/dev/null || true ;;
        Darwin) sudo umount "$MOUNT_POINT" && hdiutil detach "$LOOP_DEV" 2>/dev/null || true ;;
    esac
fi

# 8. Move to output
ts "[8/8] Finalizing..."
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
echo "    Image reports as: $BUILDINFO_LINE"
echo "    Repo: $REPO_NAME"
echo "    Git SHA: $GIT_SHA"
echo ""
echo "Next: Write to SD card with:"
echo "  ./write-to-card.sh $OUTPUT /dev/sdX"
echo ""
echo "Then boot the Pi 1B; dmz-init runs automatically."
