#!/bin/sh
# Install thermo-onboard.service for boot-time docker compose (User= you, Group=docker).
# Run on the Pi: ./install-systemd.sh
# Requires: user in group "docker", repo checkout at @@ paths resolved below.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
INSTALL_DIR="$SCRIPT_DIR"
USER_NAME="${SUDO_USER:-$USER}"
HOME_DIR="$(getent passwd "$USER_NAME" | cut -d: -f6)"

if [ "$(id -u)" -ne 0 ]; then
	echo "Run with sudo: sudo $0" >&2
	exit 1
fi

if ! getent group docker >/dev/null 2>&1; then
	echo "Group docker not found — is Docker installed?" >&2
	exit 1
fi
if ! id -nG "$USER_NAME" | tr ' ' '\n' | grep -qx docker; then
	echo "User $USER_NAME should be in group docker: sudo usermod -aG docker $USER_NAME" >&2
	exit 1
fi

sed \
	-e "s|@@INSTALL@@|$INSTALL_DIR|g" \
	-e "s|@@USER@@|$USER_NAME|g" \
	-e "s|@@HOME@@|$HOME_DIR|g" \
	"$INSTALL_DIR/thermo-onboard.service.in" >/etc/systemd/system/thermo-onboard.service

chmod 644 /etc/systemd/system/thermo-onboard.service
systemctl daemon-reload
echo "Installed /etc/systemd/system/thermo-onboard.service"
echo "Set THERMO_ENV_FILE in ~/.config/thermo-onboard/environment (e.g. THERMO_ENV_FILE=config/kitchen.env) then:"
echo "  sudo systemctl enable --now thermo-onboard"
