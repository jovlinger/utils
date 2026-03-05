#!/bin/sh
# Run the onboard container on Pi Zero 2 W.
# Pulls from GHCR if image missing; uses host network so onboard is reachable at Pi IP:5000.
#
# Prerequisites: I2C enabled (raspi-config), LIRC for /dev/lirc0 (ANAVI IR pHAT)
#
# Usage:
#   ./run-onboard.sh              # run once (auto-prep if Docker missing)
#   ./run-onboard.sh --prep        # install Docker, start daemon, then pull & run
#   ./run-onboard.sh --pull        # force pull before run
#
# Prep (--prep or when docker missing): install Docker, start daemon, pull image, start container.
# For auto-start on boot, use the systemd service (see README.md).

set -e

IMAGE="${ONBOARD_IMAGE:-ghcr.io/jovlinger/thermo-onboard:latest}"
ARG1="${1:-}"

# --- Prep: ensure Docker is installed and running ---
prep_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        echo "Docker not found. Installing..."
        curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
        sh /tmp/get-docker.sh
        rm -f /tmp/get-docker.sh
        echo "Adding $USER to docker group (log out and back in for group to take effect)"
        sudo usermod -aG docker "$USER" 2>/dev/null || true
    fi
    if ! docker info >/dev/null 2>&1; then
        echo "Starting Docker daemon..."
        sudo systemctl start docker 2>/dev/null || sudo service docker start 2>/dev/null || true
    fi
}

# Run prep when --prep or when docker unavailable
if [ "$ARG1" = "--prep" ] || ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    prep_docker
fi

# Use sudo docker if user not yet in docker group (e.g. right after install)
DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"

PULL="$ARG1"
if [ "$PULL" = "--prep" ]; then PULL=""; fi

if [ "$PULL" = "--pull" ] || ! $DOCKER image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Pulling $IMAGE..."
    $DOCKER pull "$IMAGE"
fi

# Remove existing container so we can recreate (e.g. after image update)
$DOCKER rm -f thermo-onboard 2>/dev/null || true

# Device flags: I2C (temp/humidity), LIRC (IR TX; RX optional)
DEVICES="--device /dev/i2c-1 --device /dev/lirc0"
[ -c /dev/lirc1 ] 2>/dev/null && DEVICES="$DEVICES --device /dev/lirc1"

# Host network: onboard listens on Pi's IP:5000, reachable by DMZ
$DOCKER run -d --restart unless-stopped \
    --name thermo-onboard \
    --network host \
    $DEVICES \
    -e PORT=5000 \
    "$IMAGE"

echo "Started thermo-onboard. Logs: $DOCKER logs -f thermo-onboard"
