#!/bin/sh
# Run as root on the Pi (rescue): set eth0 to 192.168.88.200/24 only, start sshd.
# Build copies ~/.ssh/id_rsa.pub into /root/.ssh/authorized_keys on the image.
#
# Usage (on Pi):
#   sh /root/network-and-sshd.sh
#   sh /root/network-and-sshd.sh 192.168.88.99   # optional other host octet .200 default below

set -e

ip_in="${1:-192.168.88.200}"
addr="${ip_in}/24"
prefix3=$(echo "$ip_in" | awk -F. 'NF==4 {print $1"."$2"."$3}')
if [ -z "$prefix3" ]; then
	echo "Error: invalid IPv4: $ip_in"
	exit 1
fi
gw="${prefix3}.1"

ip link set eth0 up
ip addr flush dev eth0 scope global
ip addr add "$addr" dev eth0
ip route flush dev eth0
ip route add default via "$gw" dev eth0

echo "nameserver $gw" >/etc/resolv.conf

echo "network updated"
ip addr show eth0

command -v sshd >/dev/null 2>&1 || {
	echo "https://dl-cdn.alpinelinux.org/alpine/v3.19/main" >/etc/apk/repositories
	echo "https://dl-cdn.alpinelinux.org/alpine/v3.19/community" >>/etc/apk/repositories
	apk update
	apk add --no-cache openssh
}

mkdir -p /root/.ssh
chmod 700 /root/.ssh
test -s /root/.ssh/authorized_keys

chmod 600 /root/.ssh/authorized_keys

ssh-keygen -A
rc-service sshd start

echo "sshd up. ssh root@${ip_in}"
