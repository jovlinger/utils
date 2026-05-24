#!/bin/sh
# Shared resolver, pubkey-only sshd (DMZ production boot and LAB rescue).
# Sourced by dmz-boot.start and /root/sshd.sh - do not execute directly.

# Read first non-comment line of network.conf: "ADDR/CIDR GATEWAY".
# Sets dmz_net_addr and dmz_net_gw; returns 0 on success.
dmz_read_network_conf() {
	dmz_net_addr=""
	dmz_net_gw=""
	_conf=""
	_SD="/media/mmcblk0"
	if [ -f "${_SD}/install/network.conf" ]; then
		_conf="${_SD}/install/network.conf"
	elif [ -f /root/network.conf ]; then
		_conf="/root/network.conf"
	fi
	if [ -z "$_conf" ]; then
		return 1
	fi
	_netline=$(grep -v '^[[:space:]]*#' "$_conf" | head -n1)
	[ -n "$_netline" ] || return 1
	# shellcheck disable=SC2086
	set -- $_netline
	dmz_net_addr="$1"
	dmz_net_gw="$2"
	[ -n "$dmz_net_addr" ] && [ -n "$dmz_net_gw" ]
}

dmz_install_resolv_conf() {
	_src=""
	_SD="/media/mmcblk0"
	if [ -f "${_SD}/install/dns.conf" ]; then
		_src="${_SD}/install/dns.conf"
	elif [ -f /root/install/dns.conf ]; then
		_src="/root/install/dns.conf"
	fi
	: >/etc/resolv.conf
	if [ -n "$_src" ]; then
		while IFS= read -r _ns || [ -n "$_ns" ]; do
			_ns=$(printf '%s' "$_ns" | sed 's/[[:space:]]*#.*//' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')
			[ -z "$_ns" ] && continue
			printf 'nameserver %s\n' "$_ns" >>/etc/resolv.conf
		done <"$_src"
	fi
	if [ ! -s /etc/resolv.conf ]; then
		printf '%s\n' 'nameserver 1.1.1.1' 'nameserver 8.8.8.8' 'nameserver 8.8.4.4' >/etc/resolv.conf
	fi
}

dmz_install_rescue_authorized_keys() {
	_SD="/media/mmcblk0"
	KEYSRC=""
	if [ -d "${_SD}/install" ] && [ -s "${_SD}/install/rescue_authorized_keys" ]; then
		KEYSRC="${_SD}/install/rescue_authorized_keys"
		echo "==> dmz sshd: pubkeys from SD FAT install/rescue_authorized_keys"
	elif [ -s /root/install/rescue_authorized_keys ]; then
		KEYSRC="/root/install/rescue_authorized_keys"
		echo "==> dmz sshd: pubkeys from /root/install/rescue_authorized_keys"
	else
		echo "Error: no rescue_authorized_keys on device." >&2
		echo "  Rebuild SD with builder ~/.ssh/*.pub (build-and-write.sh)." >&2
		return 1
	fi

	if ! grep -qE '^[[:space:]]*(ssh-|ecdsa-sha2-|ssh-ed25519|sk-ssh-|sk-ecdsa-sha2-|cert-authority)' "$KEYSRC"; then
		echo "Error: $KEYSRC has no pubkey lines." >&2
		return 1
	fi

	mkdir -p /root/.ssh
	chmod 700 /root/.ssh
	cp "$KEYSRC" /root/.ssh/authorized_keys
	chmod 600 /root/.ssh/authorized_keys
}

dmz_start_sshd_daemon() {
	SSHD_BIN=""
	for _c in /usr/sbin/sshd /sbin/sshd; do
		if [ -x "$_c" ]; then
			SSHD_BIN="$_c"
			break
		fi
	done
	if [ -z "$SSHD_BIN" ]; then
		echo "Error: sshd binary missing - rebuild SD (apkovl bundles openssh)." >&2
		return 1
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
	echo "sshd started (pubkey-only). log: tail -f $SSHD_LOG"
}
