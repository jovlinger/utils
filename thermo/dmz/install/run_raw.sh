#!/bin/sh
# Run the DMZ app from an extracted Docker rootfs without the Docker daemon.
# Uses bwrap (Bubblewrap): read-only root, tmpfs /tmp, proc, dev, share net.
#
# Assumptions: bubblewrap installed; ROOTFS_DIR is a real extracted rootfs; DMZ_BOOT_LOG
# is writable when set (default /tmp/boot.log).
#
# Usage:
#   ./run_raw.sh ROOTFS_DIR
#   ./run_raw.sh ROOTFS_DIR --debug   # shell in sandbox instead of app
#
# Started by dmz-init.start 9/12: copy to /tmp/dmz-launcher/run_raw.sh then:
#   su dmzuser -c "DMZ_BOOT_LOG=... /tmp/dmz-launcher/run_raw.sh $ROOTFS_DIR"
#
# App listens on 8080; iptables 80->8080 on host. Rootfs from image/create-image.sh.

set -e

LOG="${DMZ_BOOT_LOG:-/tmp/boot.log}"
boot_log() {
    ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    echo "$ts run_raw[$$] u=$(id -un): $*" >>"$LOG"
    [ ! -c /dev/console ] || echo "$ts run_raw: $*" >/dev/console
}

usage() {
    echo "Usage: $0 ROOTFS_DIR [--debug]"
    echo "  ROOTFS_DIR  Path to extracted rootfs (from dmz_rootfs.tar on card)"
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

boot_log "argv: $*"
boot_log "DMZ_BOOT_LOG=$LOG"

test -n "$ROOTFS" -a -d "$ROOTFS" || {
    echo "Error: ROOTFS_DIR required and must be an existing directory (got: ${ROOTFS:-empty})"
    usage
}
ROOTFS=$(cd "$ROOTFS" && pwd)
boot_log "ROOTFS=$ROOTFS"

BWRAP=$(command -v bwrap)
boot_log "bwrap=$BWRAP"

# Host /tmp/dmz.log is bind-mounted at the same path inside bwrap so dmz-init 10/12 can copy it.
touch /tmp/dmz.log
chmod 666 /tmp/dmz.log

# tini as PID 1; launcher chains pytest then run-with-stdout-logged + sh ./run.sh.
if [ -n "$DEBUG" ]; then
    printf '%s run_raw: --debug (host line for forensic)\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /tmp/dmz.log
    boot_log "exec bwrap (DEBUG shell)"
    exec "$BWRAP" --ro-bind "$ROOTFS" / --tmpfs /tmp --bind /tmp/dmz.log /tmp/dmz.log \
        --proc /proc --dev /dev --unshare-all --share-net --hostname dmz-isolation \
        --setenv PORT 8080 --chdir /app -- /bin/sh
fi

boot_log "exec bwrap -> tini -> run-with-stdout-logged -> sh ./run.sh"
exec "$BWRAP" --ro-bind "$ROOTFS" / --tmpfs /tmp --bind /tmp/dmz.log /tmp/dmz.log \
    --proc /proc --dev /dev --unshare-all --share-net --hostname dmz-isolation \
    --setenv PORT 8080 --chdir /app -- /sbin/tini -s -- sh -c 'printf "%s DMZ launcher starting %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(date)" >> /tmp/dmz.log; printf "%s DMZ pytest starting\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /tmp/dmz.log; pytest -q >> /tmp/dmz.log 2>&1; printf "%s DMZ pytest ok\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> /tmp/dmz.log; exec python ./run-with-stdout-logged.py /tmp/dmz.log 1048576 2097152 sh ./run.sh'
