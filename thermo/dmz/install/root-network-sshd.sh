#!/bin/sh
# Run as root on the Pi (rescue): set eth0 to 192.168.88.200/24 only, start sshd.
# Build merges ~/.ssh/id_ed25519.pub, id_ecdsa.pub, id_rsa.pub (each if present) into authorized_keys.
#
# Usage (on Pi):
#   sh /root/network-and-sshd.sh
#   sh /root/network-and-sshd.sh 192.168.88.99   # optional other host octet .200 default below
#
# Route flush must happen *before* `ip addr add`: flushing after add removes the kernel
# connected route for the /24, so `via $gw` fails with RTNETLINK "Network unreachable".

set -e

ip_in="${1:-192.168.88.200}"
addr="${ip_in}/24"
prefix3=$(echo "$ip_in" | awk -F. 'NF==4 {print $1"."$2"."$3}')
if [ -z "$prefix3" ]; then
	echo "Error: invalid IPv4: $ip_in"
	exit 1
fi
gw="${prefix3}.1"

echo "==> network-and-sshd: ip_in=$ip_in addr=$addr gw=$gw"
echo "==> eth0 before:"
ip -brief link show eth0 2>/dev/null || echo "    (no eth0 yet)"
ip addr show dev eth0 2>/dev/null || true
echo "==> routes on eth0 before:"
ip route show dev eth0 2>/dev/null || true

ip link set eth0 up
echo "==> eth0 link up"

ip addr flush dev eth0 scope global
echo "==> flushed global addrs on eth0"

# Clear stale routes (e.g. dhcpcd) *before* assigning the address. After `ip addr add`,
# the kernel installs a connected route for the /24; flushing here would delete it and
# break `ip route add default via $gw`.
ip route flush dev eth0 2>/dev/null || true
echo "==> flushed routes on eth0 (pre-address)"

ip addr add "$addr" dev eth0
echo "==> added $addr"
echo "==> routes on eth0 after address (expect connected /24):"
ip route show dev eth0 || true

ip route add default via "$gw" dev eth0
echo "==> default via $gw dev eth0"

echo "nameserver $gw" >/etc/resolv.conf

echo "==> network updated; eth0:"
ip addr show eth0
echo "==> full table:"
ip route show

command -v sshd >/dev/null 2>&1 || {
	# http:// avoids TLS verification failures on a minimal rootfs (no/missing CA certs, wrong time).
	echo "http://dl-cdn.alpinelinux.org/alpine/v3.19/main" >/etc/apk/repositories
	echo "http://dl-cdn.alpinelinux.org/alpine/v3.19/community" >>/etc/apk/repositories
	apk update
	apk add --no-cache openssh
}

mkdir -p /root/.ssh
chmod 700 /root/.ssh
if [ ! -s /root/.ssh/authorized_keys ]; then
	echo "Error: /root/.ssh/authorized_keys missing or empty (not baked at image build?)." >&2
	echo "  Fix: rebuild the SD image with build-and-write.sh on a host that has ~/.ssh/*.pub," >&2
	echo "  or append your key: echo 'ssh-ed25519 AAAA...' >>/root/.ssh/authorized_keys && chmod 600 /root/.ssh/authorized_keys" >&2
	exit 1
fi
chmod 600 /root/.ssh/authorized_keys

# Alpine's default sshd_config leaves password auth at compile-time defaults (often yes).
# Drop-in is loaded before the rest of sshd_config (see Include in /etc/ssh/sshd_config).
mkdir -p /etc/ssh/sshd_config.d
cat >/etc/ssh/sshd_config.d/50-dmz-rescue.conf <<'EOF'
# DMZ rescue: root login by pubkey only (/root/.ssh/authorized_keys from image build).
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
PermitRootLogin prohibit-password
AuthenticationMethods publickey
EOF

# Host keys normally preloaded from apkovl (/etc/ssh/ssh_host_*); -A only creates missing types.
ssh-keygen -A

# Avoid OpenRC sshd: it supervises/restarts and hides auth noise. Run sshd in the foreground
# (-D) under a shell background job so -e sends logs to a file you can tail and kill/restart.
# rc-service sshd start
rc-service sshd stop 2>/dev/null || true
rc-update del sshd default 2>/dev/null || true
killall sshd 2>/dev/null || true
rm -f /run/sshd.pid 2>/dev/null || true

SSHD_LOG=/var/log/sshd.log
touch "$SSHD_LOG"
chmod 644 "$SSHD_LOG"
# -ddd ≈ LogLevel DEBUG3; -e log to stderr (here redirected); -D no daemonize (stable fd with &).
sshd -D -ddd -e >>"$SSHD_LOG" 2>&1 &
echo "$!" >/run/dmz-sshd-raw.pid

echo "sshd up (pubkey only, raw debug). ssh root@${ip_in}"
echo "  log: tail -f $SSHD_LOG"
echo '  stop: kill $(cat /run/dmz-sshd-raw.pid) 2>/dev/null || killall sshd; rm -f /run/sshd.pid'
echo "  re-run this script after network is up, or: sshd -D -ddd -e >>${SSHD_LOG} 2>&1 &"
