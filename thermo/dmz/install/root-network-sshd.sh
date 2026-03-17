#!/bin/sh
# Run as root: bring up eth0 at 192.168.88.200 and start sshd.
# authorized_keys is baked into the image (one entry from install/authorized_keys at build).

set -e

ip link set eth0 up 2>/dev/null || true
ip addr add 192.168.88.200/24 dev eth0 2>/dev/null || true
ip route add default via 192.168.88.1 2>/dev/null || true
echo "nameserver 192.168.88.1" > /etc/resolv.conf

if ! command -v sshd >/dev/null 2>&1; then
    # Use http (not https) so apk doesn't need to trust the mirror TLS cert
    echo "http://dl-cdn.alpinelinux.org/alpine/v3.23/main" > /etc/apk/repositories
    echo "http://dl-cdn.alpinelinux.org/alpine/v3.23/community" >> /etc/apk/repositories
    apk update && apk add --no-cache openssh
fi

mkdir -p /root/.ssh
chmod 700 /root/.ssh
if [ ! -f /root/.ssh/authorized_keys ]; then
    touch /root/.ssh/authorized_keys
fi
chmod 600 /root/.ssh/authorized_keys 2>/dev/null || true

if [ ! -s /root/.ssh/authorized_keys ]; then
    echo "No key in /root/.ssh/authorized_keys. Add your id_rsa.pub (e.g. paste one line from Mac), then run this script again or: rc-service sshd start"
    exit 0
fi

ssh-keygen -A 2>/dev/null || true
rc-service sshd start 2>/dev/null || /usr/sbin/sshd 2>/dev/null || true
echo "sshd up. ssh root@192.168.88.200"
