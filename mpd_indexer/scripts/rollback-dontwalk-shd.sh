#!/bin/bash
# Restore stock MPD 0.23.15 on the SHD and remove dont-walk unit drop-in.
set -euo pipefail

SHD_HOST="${SHD_HOST:-192.168.88.39}"
SHD_USER="${SHD_USER:-volumiooem}"
SHD_PASS="${SHD_PASS:-}"

if [ -z "$SHD_PASS" ]; then
  echo "SHD_PASS is required." >&2
  exit 1
fi
command -v expect >/dev/null || {
  echo "expect is required" >&2
  exit 1
}

REMOTE=$(cat <<'REMOTE'
set -e
systemctl stop mpd mpd.socket 2>/dev/null || true
sleep 1
fuser -k 6600/tcp 2>/dev/null || true
test -f /usr/bin/mpd.stock-0.23.15
cp -a /usr/bin/mpd.stock-0.23.15 /usr/bin/mpd
chmod 755 /usr/bin/mpd
rm -f /etc/systemd/system/mpd.service.d/dontwalk-confpath.conf
rmdir /etc/systemd/system/mpd.service.d 2>/dev/null || true
systemctl daemon-reload
systemctl unmask mpd.socket 2>/dev/null || true
systemctl start mpd.socket
systemctl start mpd
sleep 2
systemctl is-active mpd
mpd --version 2>&1 | head -3
REMOTE
)
B64=$(printf '%s' "$REMOTE" | base64 | tr -d '\n')

expect <<EOF
set timeout 60
spawn ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no \
  ${SHD_USER}@${SHD_HOST} "echo $SHD_PASS | sudo -S -p '' bash -lc 'echo $B64 | base64 -d | bash'"
expect {
  -re "(?i)password:" { send "$SHD_PASS\r"; exp_continue }
  eof
}
EOF
echo "OK rolled back to stock 0.23.15"
