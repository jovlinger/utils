#!/bin/sh
# LAB/rescue SSH: attach eth0 to 192.168.88.x/24 (default .200), gw 192.168.88.1, public DNS (1.1.1.1 + Google),
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
# Build merges ~/.ssh/id_*.pub on the builder into those paths; sshd stays off until this script runs
# (unless dmz.conf SSHD_ON_BOOT=yes baked sshd-on-boot on the card).

set -e

. /root/install/dmz-sshd-common.sh

ROUTER_GATEWAY="${ROUTER_GATEWAY:-192.168.88.1}"
ip_main="${1:-192.168.88.200}"

if echo "$ip_main" | grep -q '^[0-9]\{1,3\}$'; then
	prefix="$(echo "$ROUTER_GATEWAY" | sed 's/\.[0-9]*$//')"
	ip_in="${prefix}.${ip_main}"
else
	ip_in="$ip_main"
fi

addr="${ip_in}/24"

echo "==> /root/sshd.sh: addr=$addr default via=$ROUTER_GATEWAY (DNS 1.1.1.1 8.8.8.8 8.8.4.4)"

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

dmz_install_resolv_conf

dmz_install_rescue_authorized_keys
dmz_start_sshd_daemon

_ip_show=$(ip -4 -o addr show dev eth0 scope global 2>/dev/null | awk '{print $4}' | head -n1)
echo "  ssh root@${_ip_show:-$ip_in}"
echo "  stop: kill \$(cat /run/dmz-sshd-raw.pid 2>/dev/null) 2>/dev/null || killall sshd"

ip addr show dev eth0 || true
ip route show || true
