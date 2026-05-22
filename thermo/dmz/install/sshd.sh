#!/bin/sh
# Rescue / manual SSH: install rescue pubkeys, configure eth0, start sshd.
#
# Production (SD install/network.conf or /root/network.conf from dmz-boot):
#   sh /root/sshd.sh
# Uses ADDR/CIDR + gateway from network.conf (same as dmz-boot eth0).
#
# LAB on MikroTik LAN only (no network.conf, or force lab):
#   sh /root/sshd.sh lab
#   sh /root/sshd.sh lab 99          # last octet .99, gw 192.168.88.1
#   sh /root/sshd.sh 192.168.88.200  # legacy: explicit LAB address
#
# Pubkey source (first match wins):
#   FAT: /media/mmcblk0/install/rescue_authorized_keys
#   apkovl: /root/install/rescue_authorized_keys

set -e

. /root/install/dmz-sshd-common.sh

_use_lab=0
_ip_arg=""
case "${1:-}" in
lab | LAB)
	_use_lab=1
	_ip_arg="${2:-192.168.88.200}"
	;;
"")
	;;
*)
	_use_lab=1
	_ip_arg="$1"
	;;
esac

if [ "$_use_lab" -eq 0 ] && dmz_read_network_conf; then
	addr="$dmz_net_addr"
	ROUTER_GATEWAY="$dmz_net_gw"
	echo "==> /root/sshd.sh: production network.conf addr=$addr via=$ROUTER_GATEWAY"
else
	ROUTER_GATEWAY="${ROUTER_GATEWAY:-192.168.88.1}"
	ip_main="${_ip_arg:-192.168.88.200}"
	if echo "$ip_main" | grep -q '^[0-9]\{1,3\}$'; then
		prefix="$(echo "$ROUTER_GATEWAY" | sed 's/\.[0-9]*$//')"
		ip_in="${prefix}.${ip_main}"
	else
		ip_in="$ip_main"
	fi
	addr="${ip_in}/24"
	echo "==> /root/sshd.sh: LAB addr=$addr default via=$ROUTER_GATEWAY (DNS from install/dns.conf or public)"
fi

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
echo "  ssh root@${_ip_show:-${addr%/*}}"
echo "  stop: kill \$(cat /run/dmz-sshd-raw.pid 2>/dev/null) 2>/dev/null || killall sshd"

ip addr show dev eth0 || true
ip route show || true
