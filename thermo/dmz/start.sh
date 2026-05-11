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

# Zone Ed25519 pub key (twoway → DMZ machine auth). Baked by build-and-write.sh --include-pub-key
# (Pi: /etc/dmz/zone-pub.pem in the chroot, copied by dmz-boot.start). Local docker can also bind
# -v $PWD/.secrets/zone/pub.pem:/etc/dmz/zone-pub.pem:ro. An explicit env wins.
if [ -z "${ZONE_PUBLIC_KEY_PATH:-}" ] && [ -z "${ZONE_PUBLIC_KEY:-}" ] && [ -f /etc/dmz/zone-pub.pem ]; then
	export ZONE_PUBLIC_KEY_PATH=/etc/dmz/zone-pub.pem
	echo "start.sh: ZONE_PUBLIC_KEY_PATH=$ZONE_PUBLIC_KEY_PATH (twoway auth enforced)"
fi

# Google OAuth + Flask session: baked by dmz-boot.start from SD install/*.txt (see ./SECRETS.md).
# Explicit env vars win. All three one-line files must exist together; otherwise we skip (avoids
# oauth_enabled with a missing client secret).
_oauth_id_f=/etc/dmz/google-client-id
_oauth_sec_f=/etc/dmz/google-client-secret
_oauth_sk_f=/etc/dmz/flask-secret-key
if [ -z "${GOOGLE_CLIENT_ID:-}" ] && [ -f "$_oauth_id_f" ] && [ -f "$_oauth_sec_f" ] && [ -f "$_oauth_sk_f" ]; then
	export GOOGLE_CLIENT_ID="$(head -n1 "$_oauth_id_f" | tr -d '\r')"
	export GOOGLE_CLIENT_SECRET="$(head -n1 "$_oauth_sec_f" | tr -d '\r')"
	export SECRET_KEY="$(head -n1 "$_oauth_sk_f" | tr -d '\r')"
	echo "start.sh: OAuth enabled from /etc/dmz/google-client-id (+ secret + flask-secret-key)"
elif [ -f "$_oauth_id_f" ] || [ -f "$_oauth_sec_f" ] || [ -f "$_oauth_sk_f" ]; then
	echo "start.sh: WARNING incomplete OAuth files under /etc/dmz (need google-client-id, google-client-secret, flask-secret-key); not loading" >&2
fi
if [ -z "${ALLOWED_EMAIL:-}" ] && [ -f /etc/dmz/allowed-email ]; then
	export ALLOWED_EMAIL="$(head -n1 /etc/dmz/allowed-email | tr -d '\r')"
	echo "start.sh: ALLOWED_EMAIL from /etc/dmz/allowed-email"
fi

mount -o remount,ro / 2>/dev/null \
	|| echo "start.sh: remount ro / not applied" >&2

exec su-exec dmz python /app/run-with-stdout-logged.py /var/log/dmz.log 1048576 2097152 /bin/sh /app/run.sh
