#!/bin/bash
# Install dont-walk MPD on miniDSP SHD (Volumio / NanoPi NEO3 armhf).
#
# Prerequisites:
#   - out/mpd from: make -C mpd_indexer build-dontwalk-armhf ...
#   - SSH to SHD as volumiooem (password auth via expect unless key works)
#
# Env:
#   SHD_HOST   default 192.168.88.39
#   SHD_USER   default volumiooem
#   SHD_PASS   required for password SSH/sudo (volumiooem password)
#   MPD_BIN    default ../out/mpd relative to this script's parent out/
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MPD_BIN="${MPD_BIN:-$ROOT/out/mpd}"
SHD_HOST="${SHD_HOST:-192.168.88.39}"
SHD_USER="${SHD_USER:-volumiooem}"
SHD_PASS="${SHD_PASS:-}"

if [ ! -f "$MPD_BIN" ]; then
  echo "missing binary: $MPD_BIN (build first)" >&2
  exit 1
fi
if [ -z "$SHD_PASS" ]; then
  echo "SHD_PASS is required (SSH + sudo password for $SHD_USER)." >&2
  exit 1
fi

command -v expect >/dev/null || {
  echo "expect is required for password SSH to SHD" >&2
  exit 1
}

echo "==> upload $MPD_BIN -> $SHD_USER@$SHD_HOST:/tmp/mpd-dontwalk-full"
expect <<EOF
set timeout 120
spawn scp -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no \
  {$MPD_BIN} ${SHD_USER}@${SHD_HOST}:/tmp/mpd-dontwalk-full
expect {
  -re "(?i)password:" { send "$SHD_PASS\r"; exp_continue }
  eof
}
EOF

# Remote install: keep stock backup, pass /etc/mpd.conf (0.23.5 default
# prefix is /usr/local/etc), keep Type=notify, start stock mpd.socket+service.
REMOTE=$(cat <<'REMOTE'
set -e
chmod +x /tmp/mpd-dontwalk-full
/tmp/mpd-dontwalk-full --version 2>&1 | head -20
ldd /tmp/mpd-dontwalk-full 2>&1 | grep -E "not found|GLIBC_[0-9]" && exit 1 || echo OK_ldd

systemctl stop mpd 2>/dev/null || true
systemctl stop mpd.socket 2>/dev/null || true
sleep 1
fuser -k 6600/tcp 2>/dev/null || true

if [ ! -f /usr/bin/mpd.stock-0.23.15 ]; then
  cp -a /usr/bin/mpd /usr/bin/mpd.stock-0.23.15
fi
cp /tmp/mpd-dontwalk-full /usr/bin/mpd
chmod 755 /usr/bin/mpd

mkdir -p /usr/local/etc
ln -sfn /etc/mpd.conf /usr/local/etc/mpd.conf

mkdir -p /etc/systemd/system/mpd.service.d
# Only override conf path; keep Type=notify from stock unit.
cat >/etc/systemd/system/mpd.service.d/dontwalk-confpath.conf <<EOF
[Service]
ExecStart=
ExecStart=/usr/bin/mpd --no-daemon /etc/mpd.conf
EOF

systemctl daemon-reload
systemctl unmask mpd.socket 2>/dev/null || true
systemctl start mpd.socket
systemctl start mpd
sleep 3
systemctl is-active mpd
mpd --version 2>&1 | head -3
mpc status 2>&1 | head -6 || true
REMOTE
)

B64=$(printf '%s' "$REMOTE" | base64 | tr -d '\n')
echo "==> install on SHD"
expect <<EOF
set timeout 90
spawn ssh -o StrictHostKeyChecking=no -o PreferredAuthentications=password -o PubkeyAuthentication=no \
  ${SHD_USER}@${SHD_HOST} "echo $SHD_PASS | sudo -S -p '' bash -lc 'echo $B64 | base64 -d | bash'"
expect {
  -re "(?i)password:" { send "$SHD_PASS\r"; exp_continue }
  eof
}
EOF

echo "==> getState"
curl -sS -m5 -o /tmp/shd-getstate-deploy.json -w 'getState=%{http_code}\n' \
  "http://${SHD_HOST}:3000/api/v1/getState" || echo getState_fail
echo "OK deploy complete. Rollback: cp /usr/bin/mpd.stock-0.23.15 /usr/bin/mpd && systemctl restart mpd"
