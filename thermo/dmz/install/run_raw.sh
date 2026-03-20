#!/bin/sh
# Run the DMZ app from an extracted Docker rootfs without the Docker daemon.
# Uses bwrap (Bubblewrap) by default, or --no-bwrap for chroot + bind-mounted app log.
#
# App stdout/stderr log (host-visible): /var/log/dmz.log (bind-mounted into chroot/bwrap).
#
# Assumptions: bubblewrap installed when not using --no-bwrap; ROOTFS_DIR is extracted
# dmz_rootfs.tar; DMZ_BOOT_LOG when set (default /tmp/boot.log).
#
# Usage:
#   ./run_raw.sh ROOTFS_DIR
#   ./run_raw.sh ROOTFS_DIR --no-bwrap   # chroot; host /var/log/dmz.log bind-mounted at same path
#
# Started by dmz-init.start 9/12: copy to /tmp/dmz-launcher/run_raw.sh then launch.

set -e

LOG="${DMZ_BOOT_LOG:-/tmp/boot.log}"
# Host path for the app log; bind-mounted at /var/log/dmz.log inside chroot/bwrap.
# Override with DMZ_APP_LOG=/path for tests or hosts where /var/log is not writable.
DMZ_APP_LOG="${DMZ_APP_LOG:-/var/log/dmz.log}"

boot_log() {
    ts=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
    echo "$ts run_raw[$$] u=$(id -un): $*" >>"$LOG"
    [ ! -c /dev/console ] || echo "$ts run_raw: $*" >/dev/console
}

usage() {
    echo "Usage: $0 ROOTFS_DIR [--no-bwrap]"
    echo "  ROOTFS_DIR  Path to extracted rootfs (from dmz_rootfs.tar on card)"
    echo "  --no-bwrap  chroot into ROOTFS; app log on host at $DMZ_APP_LOG"
    exit 1
}

ROOTFS=""
NO_BWRAP=""

for arg in "$@"; do
    case "$arg" in
        --no-bwrap) NO_BWRAP=1 ;;
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

if [ -z "$NO_BWRAP" ]; then
    BWRAP=$(command -v bwrap)
    boot_log "bwrap=$BWRAP"
fi

if ! ( umask 0; _d=$(dirname "$DMZ_APP_LOG"); mkdir -p "$_d" 2>/dev/null && touch "$DMZ_APP_LOG" 2>/dev/null ); then
    DMZ_APP_LOG="/tmp/dmz.log"
    mkdir -p "$(dirname "$DMZ_APP_LOG")"
    touch "$DMZ_APP_LOG"
fi
chmod 666 "$DMZ_APP_LOG" 2>/dev/null || true
boot_log "DMZ_APP_LOG(host)=$DMZ_APP_LOG -> /var/log/dmz.log in sandbox"

# Optional bwrap binds for DNS/hosts (host files, read-only inside sandbox).
BWRAP_ETC_BINDS=""
if [ -r /etc/resolv.conf ]; then
    BWRAP_ETC_BINDS="$BWRAP_ETC_BINDS --ro-bind /etc/resolv.conf /etc/resolv.conf"
fi
if [ -r /etc/hosts ]; then
    BWRAP_ETC_BINDS="$BWRAP_ETC_BINDS --ro-bind /etc/hosts /etc/hosts"
fi

chroot_bind_runtime() {
    # Pseudofs + host devices (typical minimal chroot for network + Python).
    mkdir -p "$ROOTFS/dev" "$ROOTFS/proc" "$ROOTFS/sys" "$ROOTFS/run" \
        "$ROOTFS/tmp" "$ROOTFS/dev/pts" "$ROOTFS/dev/shm" "$ROOTFS/var/log" \
        "$ROOTFS/etc"
    touch "$ROOTFS/var/log/dmz.log"
    mount --bind "$DMZ_APP_LOG" "$ROOTFS/var/log/dmz.log"
    mount --bind /dev "$ROOTFS/dev" 2>/dev/null || boot_log "WARN: bind /dev failed"
    mount --bind /proc "$ROOTFS/proc" 2>/dev/null || boot_log "WARN: bind /proc failed"
    mount --bind /sys "$ROOTFS/sys" 2>/dev/null || boot_log "WARN: bind /sys failed"
    mount --bind /run "$ROOTFS/run" 2>/dev/null || boot_log "WARN: bind /run failed"
    if [ -d /dev/pts ]; then
        mount --bind /dev/pts "$ROOTFS/dev/pts" 2>/dev/null || \
            mount -t devpts devpts "$ROOTFS/dev/pts" 2>/dev/null || \
            boot_log "WARN: devpts failed"
    fi
    if mount -t tmpfs -o mode=1777,nosuid,nodev,size=128m tmpfs "$ROOTFS/tmp" 2>/dev/null; then
        boot_log "chroot /tmp: tmpfs 128m"
    else
        mount --bind /tmp "$ROOTFS/tmp" 2>/dev/null || boot_log "WARN: /tmp not tmpfs nor bind"
    fi
    mount -t tmpfs -o mode=1777,nosuid,nodev,size=32m tmpfs "$ROOTFS/dev/shm" 2>/dev/null || \
        mount --bind /dev/shm "$ROOTFS/dev/shm" 2>/dev/null || true
    if [ -r /etc/resolv.conf ]; then
        mount --bind /etc/resolv.conf "$ROOTFS/etc/resolv.conf" 2>/dev/null || \
            boot_log "WARN: bind resolv.conf failed"
    fi
    if [ -r /etc/hosts ]; then
        mount --bind /etc/hosts "$ROOTFS/etc/hosts" 2>/dev/null || true
    fi
}

# no-bwrap: chroot + bind $DMZ_APP_LOG + runtime mounts
if [ -n "$NO_BWRAP" ]; then
    # Branches below use exec: this process becomes tini/sh and never returns;
    # nothing after this if-block runs on success.
    boot_log "no-bwrap: chroot + bind $DMZ_APP_LOG + runtime mounts"
    chroot_bind_runtime

    printf '%s DMZ run_raw: chroot start\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >>"$DMZ_APP_LOG"

    _tini="$ROOTFS/sbin/tini"
    if [ -x "$_tini" ]; then
        boot_log "chroot -> tini -> run-with-stdout-logged -> sh ./run.sh ($DMZ_APP_LOG)"
        exec chroot "$ROOTFS" /sbin/tini -s -- sh -c 'export PORT=8080; cd /app; printf "%s DMZ launcher starting %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(date)" >> /var/log/dmz.log; exec python ./run-with-stdout-logged.py /var/log/dmz.log 1048576 2097152 sh ./run.sh'
    fi
    boot_log "chroot (no tini) -> run-with-stdout-logged"
    exec chroot "$ROOTFS" /bin/sh -c 'export PORT=8080; cd /app; printf "%s DMZ launcher starting %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(date)" >> /var/log/dmz.log; exec python ./run-with-stdout-logged.py /var/log/dmz.log 1048576 2097152 sh ./run.sh'
fi

boot_log "exec bwrap -> tini -> run-with-stdout-logged -> sh ./run.sh ($DMZ_APP_LOG)"
# shellcheck disable=SC2086
exec "$BWRAP" --ro-bind "$ROOTFS" / --tmpfs /tmp --bind "$DMZ_APP_LOG" /var/log/dmz.log \
    --proc /proc --dev /dev $BWRAP_ETC_BINDS --unshare-all --share-net --hostname dmz-isolation \
    --setenv PORT 8080 --chdir /app -- /sbin/tini -s -- sh -c 'printf "%s DMZ launcher starting %s\n" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$(date)" >> /var/log/dmz.log; exec python ./run-with-stdout-logged.py /var/log/dmz.log 1048576 2097152 sh ./run.sh'
