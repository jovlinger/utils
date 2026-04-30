#!/bin/sh
# LAB/rescue SSH: attach eth0 to 192.168.88.x/24 (default .200), gw 192.168.88.1, DNS 1.1.1.1,
# install rescue pubkeys into /root/.ssh/authorized_keys from on-device paths, start sshd.
#
# Run from console once eth0/carrier exists:
#   sh /root/sshd.sh
# Last octet only (still /24, gw unchanged):
#   sh /root/sshd.sh 99
#
# Pubkey source (first match wins):
#   FAT: /media/mmcblk0/install/rescue_authorized_keys (editable on SD; overwritten each image build),
#   apkovl: /root/install/rescue_authorized_keys (baked at flash time from same content).
# Build merges ~/.ssh/id_*.pub on the builder into those paths; sshd stays off until this script runs.

set -e

ROUTER_GATEWAY="${ROUTER_GATEWAY:-192.168.88.1}"
ip_main="${1:-192.168.88.200}"

if echo "$ip_main" | grep -q '^[0-9]\{1,3\}$'; then
	prefix="$(echo "$ROUTER_GATEWAY" | sed 's/\.[0-9]*$//')"
	ip_in="${prefix}.${ip_main}"
else
	ip_in="$ip_main"
fi

addr="${ip_in}/24"

echo "==> /root/sshd.sh: addr=$addr default via=$ROUTER_GATEWAY (DNS 1.1.1.1)"

# Loopback: same rationale as dmz-boot.start.
ip link set lo up
ip addr add 127.0.0.1/8 dev lo 2>/dev/null || true
ip -6 addr add ::1/128 dev lo 2>/dev/null || true

echo "==> eth0 before:"
ip -brief link show eth0 2>/dev/null || echo "    (no eth0 yet)"
ip addr show dev eth0 2>/dev/null || true

ip link set eth0 up

ip addr flush dev eth0 scope global 2>/dev/null || true
ip route flush dev eth0 2>/dev/null || true

ip addr add "$addr" dev eth0
ip route add default via "$ROUTER_GATEWAY" dev eth0

printf '%s\n' "nameserver 1.1.1.1" >/etc/resolv.conf

_SD="/media/mmcblk0"
KEYSRC=""
if [ -d "${_SD}/install" ] && [ -s "${_SD}/install/rescue_authorized_keys" ]; then
	KEYSRC="${_SD}/install/rescue_authorized_keys"
	echo "==> installing pubkeys from SD FAT install/rescue_authorized_keys"
elif [ -s /root/install/rescue_authorized_keys ]; then
	KEYSRC="/root/install/rescue_authorized_keys"
	echo "==> installing pubkeys from baked /root/install/rescue_authorized_keys"
else
	echo "Error: no rescue_authorized_keys on device." >&2
	echo "  Image build must populate install/rescue_authorized_keys (from builder ~/.ssh/*.pub)." >&2
	echo "  Or mount FAT and place install/rescue_authorized_keys on the SD." >&2
	exit 1
fi

if ! grep -qE '^[[:space:]]*(ssh-|ecdsa-sha2-|ssh-ed25519|sk-ssh-|sk-ecdsa-sha2-|cert-authority)' "$KEYSRC"; then
	echo "Error: $KEYSRC has no pubkey lines (expected OpenSSH authorized_keys entries)." >&2
	exit 1
fi

mkdir -p /root/.ssh
chmod 700 /root/.ssh

cp "$KEYSRC" /root/.ssh/authorized_keys
chmod 600 /root/.ssh/authorized_keys

SSHD_BIN=""
for _c in /usr/sbin/sshd /sbin/sshd; do
	if [ -x "$_c" ]; then
		SSHD_BIN="$_c"
		break
	fi
done
if [ -z "$SSHD_BIN" ]; then
	echo "Error: sshd binary missing — rebuild SD (apkovl bundles openssh)." >&2
	exit 1
fi

mkdir -p /etc/ssh/sshd_config.d
cat >/etc/ssh/sshd_config.d/50-dmz-rescue.conf <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin prohibit-password
AuthenticationMethods publickey
LogLevel VERBOSE
EOF

ssh-keygen -A >/dev/null 2>&1 || ssh-keygen -A

rc-service sshd stop 2>/dev/null || true
rc-update del sshd default 2>/dev/null || true
killall sshd 2>/dev/null || true
rm -f /run/sshd.pid 2>/dev/null || true

SSHD_LOG=/var/log/sshd.log
touch "$SSHD_LOG"
chmod 644 "$SSHD_LOG"
"$SSHD_BIN" -D -E "$SSHD_LOG" &
echo "$!" >/run/dmz-sshd-raw.pid

echo "sshd started (pubkey-only). ssh root@${ip_in}"
echo "  log: tail -f $SSHD_LOG"
echo "  stop: kill \$(cat /run/dmz-sshd-raw.pid) 2>/dev/null || killall sshd"

ip addr show dev eth0 || true
ip route show || true
