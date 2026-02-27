#!/bin/sh
# Run the DMZ app from an extracted Docker rootfs without the Docker daemon.
# Uses bwrap (Bubblewrap) for isolation: read-only root, tmpfs for /tmp, no write access.
#
# Prerequisites on host (Alpine): apk add bubblewrap
#
# Usage:
#   ./run_raw.sh ROOTFS_DIR
#   ./run_raw.sh ROOTFS_DIR --debug   # drop to shell instead of running app
#
# Example:
#   tar -xf dmz_rootfs.tar -C /tmp/dmz_rootfs
#   ./run_raw.sh /tmp/dmz_rootfs
#
# The app listens on port 8080. Use iptables to redirect 80->8080:
#   iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080
#
# See PISEC.md, README-dmz.md. Rootfs is produced by export_rootfs.sh.

set -e

usage() {
    echo "Usage: $0 ROOTFS_DIR [--debug]"
    echo "  ROOTFS_DIR  Path to extracted rootfs (from export_rootfs.sh)"
    echo "  --debug     Start shell in sandbox instead of running the app"
    exit 1
}

ROOTFS=""
DEBUG=""

for arg in "$@"; do
    case "$arg" in
        --debug) DEBUG=1 ;;
        --help|-h) usage ;;
        *) ROOTFS="$arg" ;;
    esac
done

if [ -z "$ROOTFS" ] || [ ! -d "$ROOTFS" ]; then
    echo "Error: ROOTFS_DIR is required and must be an existing directory"
    usage
fi

ROOTFS=$(cd "$ROOTFS" && pwd)

if ! command -v bwrap >/dev/null 2>&1; then
    echo "Error: bwrap not found. On Alpine: apk add bubblewrap"
    exit 1
fi

# Sandbox: read-only rootfs, tmpfs for /tmp, proc, dev, share net, unshare rest.
# App listens on 8080 (unprivileged); iptables redirects 80->8080 on host.
if [ -n "$DEBUG" ]; then
    exec bwrap --ro-bind "$ROOTFS" / --tmpfs /tmp --proc /proc --dev /dev \
        --unshare-all --share-net --hostname dmz-isolation --setenv PORT 8080 \
        --chdir /app -- /bin/sh
else
    exec bwrap --ro-bind "$ROOTFS" / --tmpfs /tmp --proc /proc --dev /dev \
        --unshare-all --share-net --hostname dmz-isolation --setenv PORT 8080 \
        --chdir /app -- /bin/sh ./run.sh
fi
