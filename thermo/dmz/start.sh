#!/bin/sh
# Container / Pi chroot entry (root): tmpfs on /tmp only (never over all of /var/log, so a
# bind-mounted /var/log/dmz.log stays visible — same on Pi and plain docker run). Then drop to
# dmz with run-with-stdout-logged wrapping run.sh -> /var/log/dmz.log.

set -eu

mkdir -p /var/log /tmp
touch /var/log/dmz.log /var/log/startup_tests.log 2>/dev/null || true
chown dmz:dmz /var/log/dmz.log /var/log/startup_tests.log 2>/dev/null || true

mount -t tmpfs -o nosuid,nodev,size=64m tmpfs /tmp 2>/dev/null \
	|| echo "start.sh: tmpfs /tmp skipped" >&2

mount -o remount,ro / 2>/dev/null \
	|| echo "start.sh: remount ro / not applied" >&2

exec su-exec dmz python /app/run-with-stdout-logged.py /var/log/dmz.log 1048576 2097152 /bin/sh /app/run.sh
