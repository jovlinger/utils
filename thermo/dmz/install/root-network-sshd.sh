#!/bin/sh
# Run as root: bring up eth0 and start sshd (rescue / manual access).
# Assumptions: eth0 exists; openssh in image or apk reachable; /root/.ssh/authorized_keys
# has at least one key before sshd is started.
#
# Usage (on card this file is copied to /root/network-and-sshd.sh):
#   sh /root/network-and-sshd.sh <ip>
# Example:
#   sh /root/network-and-sshd.sh 192.168.77.10
#
# /24 address; gateway x.y.z.1; default route + resolv.conf via gateway.

set -e

ip_in="${1:-}"
if [ -z "$ip_in" ]; then
    echo "Usage: $0 <ip>"
    exit 1
fi

addr="${ip_in}/24"
prefix3=$(echo "$ip_in" | awk -F. 'NF==4 {print $1"."$2"."$3}')
if [ -z "$prefix3" ]; then
    echo "Error: invalid IPv4: $ip_in (e.g. 192.168.88.200)"
    exit 1
fi
gw="${prefix3}.1"

ip link set eth0 up
ip addr flush dev eth0 scope global
ip addr add "$addr" dev eth0
ip route flush dev eth0
ip route add default via "$gw" dev eth0

echo "nameserver $gw" > /etc/resolv.conf

echo "network updated"
ip addr show eth0

command -v sshd >/dev/null 2>&1 || {
    echo "http://dl-cdn.alpinelinux.org/alpine/v3.23/main" > /etc/apk/repositories
    echo "http://dl-cdn.alpinelinux.org/alpine/v3.23/community" >> /etc/apk/repositories
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
