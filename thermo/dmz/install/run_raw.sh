#!/bin/sh
# Run the DMZ app from an extracted Docker rootfs without the Docker daemon.
# Uses bwrap (Bubblewrap): read-only root, tmpfs /tmp, proc, dev, share net.
# Assumptions: bubblewrap installed; ROOTFS_DIR is a real extracted rootfs; DMZ_BOOT_LOG
# is writable when set (default /tmp/boot.log).
#
# Usage:
#   ./run_raw.sh ROOTFS_DIR
#   ./run_raw.sh ROOTFS_DIR --debug   # shell in sandbox instead of app
#   ./run_raw.sh ROOTFS_DIR --no-bwrap # run without bubblewrap (for debugging)
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
    echo "Usage: $0 ROOTFS_DIR [--debug] [--no-bwrap]"
    echo "  ROOTFS_DIR  Path to extracted rootfs (from dmz_rootfs.tar on card)"
    echo "  --debug     Start shell in sandbox instead of running the app"
    echo "  --no-bwrap  Run app without bubblewrap (plain host-process)"
    exit 1
}

ROOTFS=""
DEBUG=""
NO_BWRAP=""

for arg in "$@"; do
    case "$arg" in
        --debug) DEBUG=1 ;;
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

# Host /tmp/dmz.log is what dmz-init reads for forensic evidence.
touch /tmp/dmz.log
chmod 666 /tmp/dmz.log

if [ -n "$NO_BWRAP" ]; then
    boot_log "no-bwrap mode: plain execution (no chroot/bwrap)"
    printf '%s DMZ run_raw: plain start\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" >> /tmp/dmz.log

    APP_DIR="$ROOTFS/app"
    [ -d "$APP_DIR" ] || APP_DIR="$ROOTFS"
    cd "$APP_DIR"

    # Best-effort: make the rootfs's site-packages visible to the host python.
    PYTHONPATH_EXTRA=""
    for d in "$ROOTFS"/usr/lib/python*/site-packages "$ROOTFS"/usr/lib/python*/dist-packages "$ROOTFS"/usr/local/lib/python*/site-packages; do
        [ -d "$d" ] || continue
        if [ -z "$PYTHONPATH_EXTRA" ]; then
            PYTHONPATH_EXTRA="$d"
        else
            PYTHONPATH_EXTRA="$PYTHONPATH_EXTRA:$d"
        fi
    done
    export PYTHONPATH="$APP_DIR${PYTHONPATH_EXTRA:+:$PYTHONPATH_EXTRA}"

    PY="$(command -v python3 2>/dev/null || command -v python 2>/dev/null || true)"
    boot_log "plain python=$PY"
    if [ -z "$PY" ]; then
        boot_log "ERROR: no python3/python on host in plain mode"
        echo "ERROR: no python3/python on host in plain mode" >> /tmp/dmz.log
        exit 1
    fi

    # Optional: run pytest from PATH (prefer `pytest` over `python -m pytest`).
    _old_path=$PATH
    export PATH="$ROOTFS/usr/bin:$ROOTFS/bin:$ROOTFS/usr/local/bin:$_old_path"
    set +e
    if command -v pytest >/dev/null 2>&1; then
        pytest -q >> /tmp/dmz.log 2>&1
        pytest_rc=$?
    else
        echo "plain: pytest not in PATH (after rootfs bin dirs), skipping" >> /tmp/dmz.log
        boot_log "plain: pytest not in PATH, skipping"
        pytest_rc=0
    fi
    set -e
    export PATH="$_old_path"
    boot_log "plain pytest_rc=$pytest_rc"

    # Launch app logger + app.
    exec "$PY" ./run-with-stdout-logged.py /tmp/dmz.log 1048576 2097152 sh ./run.sh
fi

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
