#!/bin/sh
# Create stable OpenSSH host keys for Pi rescue sshd under thermo/dmz/.secrets/ssh-host/
# (gitignored). Re-run only if you intentionally want new keys (then update known_hosts).
#
# Usage (from repo):  ./install/gen-dmz-rescue-host-keys.sh
set -eu

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DMZ_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
OUT="$DMZ_DIR/.secrets/ssh-host"

mkdir -p "$OUT"
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
chmod 644 ssh_host_*.pub 2>/dev/null || true

echo "Fingerprints (add to known_hosts or verify on first connect):"
for f in ssh_host_ed25519_key ssh_host_rsa_key; do
	[ -f "$f" ] || continue
	ssh-keygen -lf "$f"
done
