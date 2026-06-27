#!/bin/sh
# Create stable OpenSSH host keys for Pi rescue sshd.
# Private keys live under thermo/priv/ssh-host/ (gitignored); public keys live
# under thermo/config/ssh-host/ for known_hosts verification.
#
# Usage (from repo):  ./install/gen-dmz-rescue-host-keys.sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DMZ_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
THERMO_DIR="$(cd "$DMZ_DIR/.." && pwd)"
OUT="$THERMO_DIR/priv/ssh-host"
PUB_OUT="$THERMO_DIR/config/ssh-host"

mkdir -p "$OUT"
mkdir -p "$PUB_OUT"
cd "$OUT"

gen_one() {
	_type="$1"
	_file="ssh_host_${_type}_key"
	if [ -f "$_file" ]; then
		echo "exists: $OUT/$_file"
		return 0
	fi
	echo "generating: $OUT/$_file"
	ssh-keygen -t "$_type" -f "$_file" -N "" -q
}

gen_one ed25519
gen_one rsa

chmod 600 ssh_host_*_key 2>/dev/null || true
for f in ssh_host_ed25519_key ssh_host_rsa_key; do
	[ -f "$f" ] || continue
	ssh-keygen -y -f "$f" >"$PUB_OUT/$f.pub"
done
chmod 644 "$PUB_OUT"/ssh_host_*.pub 2>/dev/null || true

echo "Fingerprints (add to known_hosts or verify on first connect):"
for f in ssh_host_ed25519_key ssh_host_rsa_key; do
	[ -f "$f" ] || continue
	ssh-keygen -lf "$f"
done
