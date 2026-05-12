#!/bin/sh
# One-shot: build linux/arm/v6 image, export dmz_rootfs.tar, assemble FAT .img; optionally dd to SD.
#
# !!! DO NOT CHANGE THE TARGET PLATFORM !!!
# The DMZ runs on a Raspberry Pi 1B (BCM2835, ARMv6, armhf userland under Alpine).
# Every `docker buildx build` and `docker run --platform` below MUST stay `linux/arm/v6`.
# Do NOT "fix" these to the host's native arch (e.g. linux/arm64 on Apple Silicon, or
# linux/arm/v7 because the onboard Pi uses it). The built rootfs is exported and dropped
# onto an Alpine RPi armhf SD image — anything other than armv6 will fail to boot the Pi 1B.
# If you are an LLM editing this file: keep `linux/arm/v6` literal everywhere it appears.
#
# Usage:
#   ./build-and-write.sh                                                # build dist/dmz.img (requires secrets below)
#   ./build-and-write.sh /dev/disk4                                     # macOS whole disk (or /dev/rdisk4)
#   ./build-and-write.sh /Volumes/PIBOOT                                # macOS: mounted boot volume -> whole /dev/rdiskN
#   ./build-and-write.sh /dev/sdb                                       # Linux whole disk
#   ./build-and-write.sh /run/media/you/PIBOOT                          # Linux: mount point -> parent disk (needs lsblk)
#
# Every image MUST bake zone machine auth (Ed25519 pub) and Google OAuth client files.
# Paths are fixed (no flags, no env overrides for secrets):
#   Zone pub:  thermo/dmz/.secrets/zone/pub.pem
#   OAuth dir: thermo/dmz/.secrets/oauth/  (google-client-id, google-client-secret,
#              flask-secret-key, allowed-email — see ./SECRETS.md)
#
# Prerequisites: docker (buildx), curl or wget, tar, gzip, mkfs.vfat, mcopy/mmd (mtools).
#   With a device: dd + sudo (unmount + write). macOS: brew install dosfstools mtools
#   Optional for SD write progress on macOS: brew install pv (bar + ETA; else periodic "still writing").
#
# Env (non-secret operational only):
#   DMZ_OUTPUT_IMG              Output .img path (default: dist/dmz.img). Used by tests.
#
# ~/.ssh/id_ed25519.pub, id_ecdsa.pub, id_rsa.pub — at least one required: merged into
# install/rescue_authorized_keys on FAT and apkovl /root/install/ (installed by console sh /root/sshd.sh).

set -eu

# Refuse to run under sudo. macOS Docker Desktop shares /var/folders/<userhash>/T/ for
# the *user* but not root; mktemp -d under sudo produces a path Docker cannot bind-mount
# correctly (the apkovl `chown` step then fails with "No such file or directory" on
# /overlay/root). The script asks for `sudo -v` itself, then uses `sudo` only for
# `diskutil unmount` and `dd`. Run as your normal user.
if [ "$(id -u)" = "0" ] && [ -n "${SUDO_USER:-}" ]; then
	echo "Error: do not run $0 under sudo." >&2
	echo "  Run as your normal user; the script will prompt for sudo when it needs to" >&2
	echo "  unmount and dd to the SD card. Re-invoke without 'sudo':" >&2
	echo "    cd $(dirname "$0") && ./$(basename "$0") $*" >&2
	exit 2
fi

usage() {
	echo "Usage: $0 [BLOCK_DEVICE_OR_MOUNT]" >&2
	echo "  Builds dist/dmz.img (or DMZ_OUTPUT_IMG) with zone machine auth + OAuth files ALWAYS baked." >&2
	echo "  Secrets are ONLY read from .secrets/zone/pub.pem and .secrets/oauth/ under thermo/dmz/ (see ./SECRETS.md)." >&2
	echo "  No overrides: missing or invalid material aborts the build." >&2
	echo "  With device or mount: background unmount during build, then sudo dd." >&2
	echo "  Examples: $0    $0 /dev/disk4    $0 /Volumes/PIBOOT" >&2
	exit 2
}

WRITE_DEV=""
while [ $# -gt 0 ]; do
	case "$1" in
	-h | --help)
		usage
		;;
	"")
		shift
		;;
	/*)
		if [ -n "$WRITE_DEV" ]; then
			echo "Error: unexpected extra argument '$1' (at most one BLOCK_DEVICE)" >&2
			exit 2
		fi
		WRITE_DEV="$1"
		shift
		;;
	*)
		echo "Error: unrecognized argument '$1' (optional BLOCK_DEVICE must be an absolute path; use --help)" >&2
		exit 2
		;;
	esac
done

# Fixed product constants (change only by editing this file).
IMAGE_SIZE_MB=256
DOCKER_IMAGE="jovlinger/thermo/dmz:armv6"
ALPINE_VERSION="3.19.0"
ALPINE_BRANCH="v3.19"
ALPINE_RPI_TAR="alpine-rpi-${ALPINE_VERSION}-armhf.tar.gz"
ALPINE_MIRROR="https://dl-cdn.alpinelinux.org/alpine"

ts() {
	echo "[$(date '+%H:%M:%S')] $*"
}

# macOS: dosfstools + mtools often off PATH
case "$(uname)" in
Darwin)
	for d in /opt/homebrew/sbin /usr/local/sbin; do
		[ -d "$d" ] && PATH="$d:$PATH"
	done
	;;
esac

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DMZ_DIR="$SCRIPT_DIR"
REPO_ROOT="$(cd "$DMZ_DIR/../.." && pwd)"
RUN_WITH_BIN="${DMZ_RUN_WITH_SRC:-$DMZ_DIR/../../bin/run-with-stdout-logged.py}"
OUTPUT_IMG="${DMZ_OUTPUT_IMG:-$DMZ_DIR/dist/dmz.img}"

# Zone public key: fixed path only (required).
ZONE_PUB_KEY_SRC="$DMZ_DIR/.secrets/zone/pub.pem"
if [ ! -f "$ZONE_PUB_KEY_SRC" ]; then
	echo "Error: zone public key PEM is required (twoway → DMZ machine auth is always baked into this image)." >&2
	echo "       Required path: $ZONE_PUB_KEY_SRC" >&2
	echo "       Generate:       make -C thermo/dmz zone-keys" >&2
	exit 1
fi
if ! head -n1 "$ZONE_PUB_KEY_SRC" | grep -q -- "-----BEGIN PUBLIC KEY-----"; then
	echo "Error: $ZONE_PUB_KEY_SRC does not look like a PEM public key" >&2
	echo "       (expected first line: -----BEGIN PUBLIC KEY-----)" >&2
	exit 1
fi

# OAuth directory: fixed path only (required).
OAUTH_DIR_SRC="$DMZ_DIR/.secrets/oauth"
if [ ! -d "$OAUTH_DIR_SRC" ]; then
	echo "Error: OAuth client directory is required (human Google login for DMZ UI is always baked into this image)." >&2
	echo "       Required path: $OAUTH_DIR_SRC/" >&2
	echo "       See: ./SECRETS.md" >&2
	exit 1
fi
for _need in google-client-id google-client-secret flask-secret-key allowed-email; do
	if [ ! -f "$OAUTH_DIR_SRC/$_need" ]; then
		echo "Error: OAuth directory missing required file $_need in $OAUTH_DIR_SRC (see ./SECRETS.md)" >&2
		exit 1
	fi
done

UMOUNT_LOG=""
UM_PID=""
DEV=""
DEV_CHECK=""

if [ -n "$WRITE_DEV" ]; then
	WRITE_SRC="$WRITE_DEV"
	if [ ! -e "$WRITE_SRC" ]; then
		echo "Error: $WRITE_SRC does not exist." >&2
		exit 1
	fi
	# Mount point (e.g. /Volumes/PIBOOT): df -> /dev/disk4s1 or /dev/disk4 -> whole /dev/rdiskN for dd.
	if [ ! -b "$WRITE_SRC" ]; then
		if [ ! -d "$WRITE_SRC" ]; then
			echo "Error: $WRITE_SRC is not a block device or a directory (mount point)." >&2
			exit 1
		fi
		_df_fs=$(LC_ALL=C df -P "$WRITE_SRC" 2>/dev/null | tail -n1 | awk '{print $1}')
		if [ -z "$_df_fs" ]; then
			echo "Error: could not resolve backing device for $WRITE_SRC (df)." >&2
			exit 1
		fi
		case "$(uname)" in
		Darwin)
			case "$WRITE_SRC" in
			/Volumes/*) ;;
			*)
				echo "Error: on macOS pass /dev/diskN, /dev/rdiskN, or a mount under /Volumes/ (got $WRITE_SRC)." >&2
				exit 1
				;;
			esac
			case "$_df_fs" in
			/dev/disk*)
				_diskrest="${_df_fs#/dev/disk}"
				case "$_diskrest" in
				*s*)
					_disknum="${_diskrest%%s*}"
					WRITE_DEV="/dev/rdisk${_disknum}"
					;;
				*)
					WRITE_DEV="/dev/rdisk${_diskrest}"
					;;
				esac
				;;
			*)
				echo "Error: unexpected df device '$_df_fs' for $WRITE_SRC (expected /dev/disk*)." >&2
				exit 1
				;;
			esac
			;;
		*)
			case "$_df_fs" in
			/dev/sda | /dev/sda* | /dev/nvme* | /dev/vda | /dev/vda*)
				echo "Error: refusing to write system-looking resolved device $_df_fs" >&2
				exit 1
				;;
			esac
			if ! command -v lsblk >/dev/null 2>&1; then
				echo "Error: lsblk not found; cannot resolve mount $WRITE_SRC to a whole disk. Pass /dev/sdX explicitly." >&2
				exit 1
			fi
			_pk=$(lsblk -ndo PKNAME -- "$_df_fs" 2>/dev/null | awk 'NR==1 { print; exit }')
			if [ -z "$_pk" ]; then
				echo "Error: lsblk could not find parent disk for $_df_fs (mount $WRITE_SRC)." >&2
				exit 1
			fi
			WRITE_DEV="/dev/${_pk}"
			;;
		esac
		if [ "$WRITE_SRC" != "$WRITE_DEV" ]; then
			ts "write target: mount $WRITE_SRC -> $WRITE_DEV (df: $_df_fs)"
		fi
	fi
	DEV="$WRITE_DEV"
	case "$DEV" in
	/dev/sda | /dev/sda* | /dev/nvme* | /dev/vda | /dev/vda*)
		echo "Error: refusing to write system-looking device $DEV" >&2
		exit 1
		;;
	esac

	# macOS: mount(8) lists /dev/diskNsM, not rdisk — use this for "still mounted?" checks.
	DEV_CHECK="$DEV"
	case "$(uname)" in
	Darwin)
		case "$DEV_CHECK" in
		/dev/rdisk*)
			DEV_CHECK="/dev/disk${DEV_CHECK#/dev/rdisk}"
			;;
		esac
		;;
	esac

	echo "sudo is required for unmounting $DEV and for dd."
	if ! sudo -v; then
		echo "Error: sudo credentials required." >&2
		exit 1
	fi

	# Unmount in the background while Docker/build steps run (high latency on some hosts).
	UMOUNT_LOG="$(mktemp "${TMPDIR:-/tmp}/dmz-umount.XXXXXX")"
	(
		u=0
		while [ "$u" -lt 60 ]; do
			case "$(uname)" in
			Darwin)
				if mount | grep -F "$DEV_CHECK" >/dev/null 2>&1; then
					sudo diskutil unmountDisk "$DEV_CHECK" >/dev/null 2>&1 \
						|| sudo diskutil unmountDisk force "$DEV_CHECK" >/dev/null 2>&1 \
						|| true
				fi
				;;
			*)
				if command -v lsblk >/dev/null 2>&1; then
					for m in $(lsblk -nr -o MOUNTPOINT "$DEV" 2>/dev/null); do
						[ -n "$m" ] && [ "$m" != "-" ] || continue
						sudo umount "$m" 2>/dev/null || sudo umount -f "$m" 2>/dev/null || true
					done
				fi
				for p in "${DEV}"*; do
					[ -e "$p" ] || continue
					[ "$p" = "$DEV" ] && continue
					sudo umount "$p" 2>/dev/null || sudo umount -f "$p" 2>/dev/null || true
				done
				sudo umount "$DEV" 2>/dev/null || true
				;;
			esac
			mount | grep -F "$DEV_CHECK" >/dev/null 2>&1 || exit 0
			sleep 3
			u=$((u + 1))
		done
		exit 1
	) >"$UMOUNT_LOG" 2>&1 &
	UM_PID=$!
fi

WORKDIR="$(mktemp -d)"
cleanup() {
	[ -n "$UMOUNT_LOG" ] && rm -f "$UMOUNT_LOG" 2>/dev/null || true
	rm -rf "$WORKDIR" 2>/dev/null || true
}
trap 'cleanup' EXIT INT TERM

# Pi rescue: merge every present standard pubkey (RSA-only images broke ed25519-primary laptops).
RESCUE_AUTH_KEYS="$WORKDIR/rescue_authorized_keys.tmp"
: >"$RESCUE_AUTH_KEYS"
RESCUE_KEY_SRC=""
for _n in id_ed25519 id_ecdsa id_rsa; do
	_k="${HOME}/.ssh/${_n}.pub"
	if [ -f "$_k" ]; then
		# .pub files already end with newline; do not append another (avoids blank lines).
		cat "$_k" >>"$RESCUE_AUTH_KEYS"
		RESCUE_KEY_SRC="${RESCUE_KEY_SRC}${RESCUE_KEY_SRC:+ }${_n}.pub"
	fi
done
if [ ! -s "$RESCUE_AUTH_KEYS" ]; then
	echo "Error: no ~/.ssh/{id_ed25519,id_ecdsa,id_rsa}.pub on build host — required to populate on-device install/rescue_authorized_keys (copy to SD + apkovl /root/install/ for /root/sshd.sh)." >&2
	exit 1
fi
ts "[build] rescue_authorized_keys from: $RESCUE_KEY_SRC"

if [ -n "$WRITE_DEV" ]; then
	ts "==> DMZ bootable image (write $DEV; background unmount pid=$UM_PID)"
else
	ts "==> DMZ bootable image (no SD write; pass block device to dd after build)"
fi
echo "    out: $OUTPUT_IMG"
echo "    size: ${IMAGE_SIZE_MB}MB  platform: linux/arm/v6"
echo "    zone pub key: $ZONE_PUB_KEY_SRC -> install/zone-pub.pem (twoway → DMZ auth, always)"
echo "    OAuth files: $OAUTH_DIR_SRC -> install/{google-client-id,google-client-secret,flask-secret-key,allowed-email}"
echo ""

if ! command -v docker >/dev/null 2>&1; then
	echo "Error: docker not found." >&2
	exit 1
fi

ts "[0/7] stage .docker-import (bin/run-with-stdout-logged.py)"
"$DMZ_DIR/stage-docker-import.sh"

ts "[1/7] docker buildx (linux/arm/v6)..."
docker buildx build \
	--platform linux/arm/v6 \
	-t "$DOCKER_IMAGE" \
	--load \
	-f "$DMZ_DIR/Dockerfile" \
	"$DMZ_DIR"
ts "[1/7] done."

ROOTFS_TAR="$WORKDIR/dmz_rootfs.tar"
ts "[2/7] docker export -> dmz_rootfs.tar"
cid=$(docker create --platform linux/arm/v6 --entrypoint /bin/true "$DOCKER_IMAGE")
docker export "$cid" >"$ROOTFS_TAR"
docker rm -f "$cid" >/dev/null 2>&1 || true
ts "[2/7] done ($(du -sh "$ROOTFS_TAR" | awk '{print $1}'))."

ts "[3/7] download Alpine Raspberry Pi armhf $ALPINE_RPI_TAR"
ALPINE_URL="${ALPINE_MIRROR}/${ALPINE_BRANCH}/releases/armhf/${ALPINE_RPI_TAR}"
ALPINE_SHA_URL="${ALPINE_URL}.sha256"
if command -v curl >/dev/null 2>&1; then
	curl -fsSL -o "$WORKDIR/$ALPINE_RPI_TAR" "$ALPINE_URL"
	curl -fsSL -o "$WORKDIR/${ALPINE_RPI_TAR}.sha256" "$ALPINE_SHA_URL"
else
	wget -q -O "$WORKDIR/$ALPINE_RPI_TAR" "$ALPINE_URL"
	wget -q -O "$WORKDIR/${ALPINE_RPI_TAR}.sha256" "$ALPINE_SHA_URL"
fi
(cd "$WORKDIR" && sha256sum -c "${ALPINE_RPI_TAR}.sha256" 2>/dev/null) || \
	(cd "$WORKDIR" && shasum -a 256 -c "${ALPINE_RPI_TAR}.sha256" 2>/dev/null) || true
ts "[3/7] done."

ALPINE_EXTRACT="$WORKDIR/alpine_extract"
mkdir -p "$ALPINE_EXTRACT"
ts "[4/7] extract Alpine RPi tarball"
tar -xzf "$WORKDIR/$ALPINE_RPI_TAR" -C "$ALPINE_EXTRACT"
ts "[4/7] done."

ts "[5/7] fetch haveged.apk + APKINDEX (apkovl payload)"
PKGDIR="$WORKDIR/pkgs"
mkdir -p "$PKGDIR"
docker run --rm --platform linux/arm/v6 \
	-v "$PKGDIR:/out" \
	alpine:3.19 \
	sh -c "printf '%s\n' '${ALPINE_MIRROR}/${ALPINE_BRANCH}/main' '${ALPINE_MIRROR}/${ALPINE_BRANCH}/community' > /etc/apk/repositories && apk update && apk fetch --recursive -o /out haveged openssh"
if command -v curl >/dev/null 2>&1; then
	curl -fsSL "${ALPINE_MIRROR}/${ALPINE_BRANCH}/main/armhf/APKINDEX.tar.gz" -o "$PKGDIR/APKINDEX-main.tar.gz"
	curl -fsSL "${ALPINE_MIRROR}/${ALPINE_BRANCH}/community/armhf/APKINDEX.tar.gz" -o "$PKGDIR/APKINDEX-community.tar.gz"
else
	wget -q -O "$PKGDIR/APKINDEX-main.tar.gz" "${ALPINE_MIRROR}/${ALPINE_BRANCH}/main/armhf/APKINDEX.tar.gz"
	wget -q -O "$PKGDIR/APKINDEX-community.tar.gz" "${ALPINE_MIRROR}/${ALPINE_BRANCH}/community/armhf/APKINDEX.tar.gz"
fi
ts "[5/7] done."

ts "[6/7] apkovl (haveged + dmz-boot + OpenRC local + rescue ssh)"
APKOVL_DIR="$WORKDIR/apkovl"
mkdir -p "$APKOVL_DIR"
if [ -d "$ALPINE_EXTRACT/lib/modules" ]; then
	mkdir -p "$APKOVL_DIR/lib"
	cp -a "$ALPINE_EXTRACT/lib/modules" "$APKOVL_DIR/lib/"
fi
docker run --rm --platform linux/arm/v6 \
	-v "$APKOVL_DIR:/overlay" \
	-v "$PKGDIR:/pkgs:ro" \
	alpine:3.19 \
	sh -c 'for f in /pkgs/*.apk; do [ -f "$f" ] && tar -xzf "$f" -C /overlay; done'
# Alpine openssh installs default OpenRC sshd symlinks — sshd must stay stopped until `/root/sshd.sh`.
find "$APKOVL_DIR/etc/runlevels" -type l \( -name 'sshd' -o -name 'sshd*' \) -delete 2>/dev/null || true
# --recursive fetch pulls in musl, openssl, zlib which are already in the pinned Alpine RPi 3.19.0
# base image.  Overlaying them with packages from the docker-side alpine:3.19 (currently 3.19.9)
# replaces the HOST dynamic linker (/lib/ld-musl-armhf.so.1) with a different patch-release
# version, which breaks chroot execution on real ARMv6 hardware.  Strip them from the overlay.
rm -f \
	"$APKOVL_DIR/lib/ld-musl-armhf.so.1" \
	"$APKOVL_DIR/lib/libc.musl-armhf.so.1" \
	"$APKOVL_DIR/lib/libcrypto.so.3" \
	"$APKOVL_DIR/lib/libssl.so.3" \
	"$APKOVL_DIR/lib/libz.so.1" \
	"$APKOVL_DIR/lib/libz.so."*

mkdir -p "$APKOVL_DIR/etc/local.d" "$APKOVL_DIR/etc/runlevels/default" "$APKOVL_DIR/etc/apk"
cp "$DMZ_DIR/install/dmz-boot.start" "$APKOVL_DIR/etc/local.d/dmz-boot.start"
chmod +x "$APKOVL_DIR/etc/local.d/dmz-boot.start"
ln -sf ../../init.d/local "$APKOVL_DIR/etc/runlevels/default/local"
: >"$APKOVL_DIR/etc/apk/repositories"
: >"$APKOVL_DIR/etc/apk/world"
echo "dmz" >"$APKOVL_DIR/etc/hostname"

# Stable rescue sshd host keys (gitignored .secrets/); avoids known_hosts churn each flash.
SECRETS_SSH="$DMZ_DIR/.secrets/ssh-host"
if [ ! -f "$SECRETS_SSH/ssh_host_ed25519_key" ]; then
	ts "[6/7] first-time: generating rescue SSH host keys -> $SECRETS_SSH"
	"$DMZ_DIR/install/gen-dmz-rescue-host-keys.sh"
fi
if [ ! -f "$SECRETS_SSH/ssh_host_ed25519_key" ] || [ ! -f "$SECRETS_SSH/ssh_host_rsa_key" ]; then
	echo "Error: missing host keys under $SECRETS_SSH (run install/gen-dmz-rescue-host-keys.sh)." >&2
	exit 1
fi
mkdir -p "$APKOVL_DIR/etc/ssh"
cp "$SECRETS_SSH/ssh_host_ed25519_key" "$SECRETS_SSH/ssh_host_ed25519_key.pub" \
	"$SECRETS_SSH/ssh_host_rsa_key" "$SECRETS_SSH/ssh_host_rsa_key.pub" \
	"$APKOVL_DIR/etc/ssh/"
chmod 600 "$APKOVL_DIR/etc/ssh/ssh_host_ed25519_key" "$APKOVL_DIR/etc/ssh/ssh_host_rsa_key"
chmod 644 "$APKOVL_DIR/etc/ssh/ssh_host_ed25519_key.pub" "$APKOVL_DIR/etc/ssh/ssh_host_rsa_key.pub"

mkdir -p "$APKOVL_DIR/root/.ssh" "$APKOVL_DIR/root/install"
cp "$DMZ_DIR/install/sshd.sh" "$APKOVL_DIR/root/sshd.sh"
chmod +x "$APKOVL_DIR/root/sshd.sh"
cp "$RESCUE_AUTH_KEYS" "$APKOVL_DIR/root/install/rescue_authorized_keys"
chmod 644 "$APKOVL_DIR/root/install/rescue_authorized_keys"
: >"$APKOVL_DIR/root/.ssh/authorized_keys"
chmod 600 "$APKOVL_DIR/root/.ssh/authorized_keys"

if command -v sha256sum >/dev/null 2>&1; then
	BUILD_HASH=$(
		{
			cat "$DMZ_DIR/build-and-write.sh" "$DMZ_DIR/Dockerfile" "$DMZ_DIR/requirements.txt" \
				"$DMZ_DIR/start.sh" "$DMZ_DIR/run.sh" "$RUN_WITH_BIN"
			for f in "$DMZ_DIR/install/dmz-boot.start" "$DMZ_DIR/install/network.conf" \
				"$DMZ_DIR/install/sshd.sh" \
				"$DMZ_DIR/install/CARD-README.txt" "$DMZ_DIR/install/README.md"; do
				[ -f "$f" ] && cat "$f"
			done
		} | sha256sum | awk '{print $1}'
	)
else
	BUILD_HASH=$(
		{
			cat "$DMZ_DIR/build-and-write.sh" "$DMZ_DIR/Dockerfile" "$DMZ_DIR/requirements.txt" \
				"$DMZ_DIR/start.sh" "$DMZ_DIR/run.sh" "$RUN_WITH_BIN"
			for f in "$DMZ_DIR/install/dmz-boot.start" "$DMZ_DIR/install/network.conf" \
				"$DMZ_DIR/install/sshd.sh" \
				"$DMZ_DIR/install/CARD-README.txt" "$DMZ_DIR/install/README.md"; do
				[ -f "$f" ] && cat "$f"
			done
		} | shasum -a 256 | awk '{print $1}'
	)
fi
BUILD_ID=$(echo "$BUILD_HASH" | cut -c1-8 | tr '[:lower:]' '[:upper:]')
BUILD_DATE=$(date -u +"%Y-%m-%dT%H:%M:%SZ")
BUILDINFO_LINE="${BUILD_ID} ${BUILD_DATE}"
GIT_SHA=$(git -C "$REPO_ROOT" rev-parse --short=12 HEAD 2>/dev/null || echo "unknown")
REPO_NAME=$(basename "$REPO_ROOT")
{
	echo "$BUILDINFO_LINE"
	echo "repo=$REPO_NAME"
	echo "git_sha=$GIT_SHA"
	_zone_pub_sha=$(
		(sha256sum "$ZONE_PUB_KEY_SRC" 2>/dev/null \
			|| shasum -a 256 "$ZONE_PUB_KEY_SRC") | awk '{print $1}'
	)
	echo "zone_pub_sha256=$_zone_pub_sha"
	echo "zone_machine_auth=baked"
	echo "oauth_client_files=baked"
} >"$WORKDIR/buildinfo.txt"

mkdir -p "$APKOVL_DIR/root"
{
	echo "DMZ $BUILDINFO_LINE"
	echo "Repo: $REPO_NAME  Git: $GIT_SHA"
	echo "Boot: /etc/local.d/dmz-boot.start"
	echo "Rescue: sh /root/sshd.sh  (LAB 192.168.88.0/24; installs install/rescue_authorized_keys then sshd)"
} >"$APKOVL_DIR/root/README"

echo "DMZ $BUILDINFO_LINE" >"$APKOVL_DIR/etc/issue"

# macOS Docker Desktop: chown inside a container does NOT update UIDs on the macOS
# host filesystem (virtiofs / osxfs bridge does not propagate UID changes back). So
# we must also run tar inside the same container — that way Linux bakes 0:0 into the
# archive rather than the macOS build user's UID (typically 501/dialout on Linux).
ts "[6/7] apkovl ownership+modes+tar (root:root under /root, /etc/ssh)"
docker run --rm \
	-v "$APKOVL_DIR:/overlay" \
	-v "$WORKDIR:/out" \
	alpine:3.19 sh -c '
set -e
chown -R 0:0 /overlay/root
chown -R 0:0 /overlay/etc/ssh
chmod 700 /overlay/root/.ssh
chmod 600 /overlay/root/.ssh/authorized_keys
chmod 755 /overlay/root/install
chmod 644 /overlay/root/install/rescue_authorized_keys
chmod 755 /overlay/root/sshd.sh
test -f /overlay/root/README && chmod 644 /overlay/root/README
chmod 600 /overlay/etc/ssh/ssh_host_ed25519_key /overlay/etc/ssh/ssh_host_rsa_key 2>/dev/null || true
chmod 644 /overlay/etc/ssh/ssh_host_ed25519_key.pub /overlay/etc/ssh/ssh_host_rsa_key.pub 2>/dev/null || true
tar -czf /out/dmz.apkovl.tar.gz -C /overlay .
'
ts "[6/7] done."

ts "[7/7] FAT image (mkfs.vfat + mtools)"
IMG_FILE="$WORKDIR/dmz.img"
dd if=/dev/zero of="$IMG_FILE" bs=1M count="$IMAGE_SIZE_MB" 2>/dev/null
mkfs.vfat -n PIBOOT -F 32 "$IMG_FILE" 2>/dev/null || mkfs.vfat -F 32 "$IMG_FILE"

if ! command -v mcopy >/dev/null 2>&1 || ! command -v mmd >/dev/null 2>&1; then
	echo "Error: install mtools (e.g. brew install mtools)." >&2
	exit 1
fi

n=0
for x in "$ALPINE_EXTRACT"/*; do
	[ -e "$x" ] || continue
	n=$((n + 1))
	ts "    mcopy $n: $(basename "$x")"
	mcopy -i "$IMG_FILE" -s "$x" "::$(basename "$x")"
done
mcopy -i "$IMG_FILE" "$ROOTFS_TAR" ::dmz_rootfs.tar
mmd -i "$IMG_FILE" ::install
mmd -i "$IMG_FILE" ::debug
for f in "$DMZ_DIR/install"/*; do
	[ -e "$f" ] || continue
	mcopy -i "$IMG_FILE" "$f" "::install/$(basename "$f")"
done
cp "$RESCUE_AUTH_KEYS" "$WORKDIR/device-rescue_authorized_keys"
mcopy -i "$IMG_FILE" "$WORKDIR/device-rescue_authorized_keys" ::install/rescue_authorized_keys
mcopy -i "$IMG_FILE" "$WORKDIR/buildinfo.txt" ::install/buildinfo.txt
mcopy -i "$IMG_FILE" "$WORKDIR/buildinfo.txt" ::BUILD.txt
mcopy -i "$IMG_FILE" "$DMZ_DIR/install/CARD-README.txt" ::README.txt
# Zone pub + OAuth: always baked (paths resolved and validated at start of script).
mcopy -i "$IMG_FILE" "$ZONE_PUB_KEY_SRC" ::install/zone-pub.pem
for _o in google-client-id google-client-secret flask-secret-key allowed-email; do
	mcopy -i "$IMG_FILE" "$OAUTH_DIR_SRC/$_o" "::install/$_o"
done
mcopy -i "$IMG_FILE" "$WORKDIR/dmz.apkovl.tar.gz" ::dmz.apkovl.tar.gz
mcopy -i "$IMG_FILE" "$WORKDIR/dmz.apkovl.tar.gz" ::alpine.apkovl.tar.gz
ts "[7/7] mcopy done."

mkdir -p "$(dirname "$OUTPUT_IMG")"
mv "$IMG_FILE" "$OUTPUT_IMG"

if command -v sha256sum >/dev/null 2>&1; then
	SHA=$(sha256sum "$OUTPUT_IMG" | awk '{print $1}')
else
	SHA=$(shasum -a 256 "$OUTPUT_IMG" | awk '{print $1}')
fi

echo ""
echo "==> Image ready: $OUTPUT_IMG"
echo "    SHA256: $SHA"
echo "    Build: $BUILDINFO_LINE"
echo ""

if [ -z "$WRITE_DEV" ]; then
	echo "SD write skipped. To flash: sudo dd if=$OUTPUT_IMG of=/dev/diskN bs=1m conv=sync  # macOS"
	echo "                         or: sudo dd if=$OUTPUT_IMG of=/dev/sdX bs=4M conv=fsync    # Linux"
	exit 0
fi

ts "waiting for background unmount (pid=$UM_PID)..."
UM_RC=0
wait "$UM_PID" || UM_RC=$?
if [ "$UM_RC" -ne 0 ]; then
	echo "Warning: background unmount exited $UM_RC; log:" >&2
	sed 's/^/  /' "$UMOUNT_LOG" >&2 || true
fi
if mount | grep -F "$DEV_CHECK" >/dev/null 2>&1; then
	echo "Error: $DEV still has mounted volumes after unmount loop." >&2
	echo "Unmount log:" >&2
	sed 's/^/  /' "$UMOUNT_LOG" >&2 || true
	exit 1
fi

IMG_SIZE=$(stat -f%z "$OUTPUT_IMG" 2>/dev/null || stat -c%s "$OUTPUT_IMG" 2>/dev/null)
DEV_SIZE=$(blockdev --getsize64 "$DEV" 2>/dev/null || echo "")
if [ -n "$DEV_SIZE" ] && [ "$IMG_SIZE" -gt "$DEV_SIZE" ]; then
	echo "Error: image ($IMG_SIZE) larger than $DEV ($DEV_SIZE)." >&2
	exit 1
fi

echo "Writing $OUTPUT_IMG -> $DEV (sudo)..."
case "$(uname)" in
Darwin)
	if command -v pv >/dev/null 2>&1; then
		# Size hint so pv can show % and ETA (brew install pv).
		pv -s "$IMG_SIZE" -f -p -t -e -r "$OUTPUT_IMG" | sudo dd of="$DEV" bs=1m conv=sync
	else
		echo "Tip: install pv for a live progress bar: brew install pv" >&2
		sudo dd if="$OUTPUT_IMG" of="$DEV" bs=1m conv=sync &
		_dd_pid=$!
		while kill -0 "$_dd_pid" 2>/dev/null; do
			sleep 20
			echo "… still writing to $DEV ($(date +%H:%M:%S))" >&2
		done
		wait "$_dd_pid"
	fi
	;;
*)
	# GNU coreutils dd: periodic kernel progress lines.
	sudo dd if="$OUTPUT_IMG" of="$DEV" bs=4M status=progress conv=fsync
	;;
esac

echo ""
echo "Done. Insert SD in Pi 1B and power on."
