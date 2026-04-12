#!/bin/sh
# Container / Pi chroot entry (root): tmpfs on /tmp only (never over all of /var/log in Docker,
# so /var/log/dmz.log stays a normal file for log rotation). Pi: dmz-boot mounts chroot var/log
# tmpfs and symlinks host /var/log/dmz.log to that file. Then su-exec dmz + run-with-stdout-logged.

set -eu

mkdir -p /var/log /tmp
touch /var/log/dmz.log /var/log/startup_tests.log 2>/dev/null || true
chown dmz:dmz /var/log/dmz.log /var/log/startup_tests.log 2>/dev/null || true

mount -t tmpfs -o nosuid,nodev,size=64m tmpfs /tmp 2>/dev/null \
	|| echo "start.sh: tmpfs /tmp skipped" >&2

mount -o remount,ro / 2>/dev/null \
	|| echo "start.sh: remount ro / not applied" >&2

exec su-exec dmz python /app/run-with-stdout-logged.py /var/log/dmz.log 1048576 2097152 /bin/sh /app/run.sh
