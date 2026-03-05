#!/bin/sh
# Run the onboard container on Pi Zero 2 W.
# Pulls from GHCR if image missing; uses host network so onboard is reachable at Pi IP:5000.
#
# Install and run:
#   scp -r thermo/onboard/install pi@pizero.local:~/thermo-onboard-install
#   ssh pi@pizero.local 'cd ~/thermo-onboard-install && chmod +x run-onboard.sh && ./run-onboard.sh --pull'
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

INSTALL_DIR="$(cd "$(dirname "$0")" && pwd)"
IMAGE="${ONBOARD_IMAGE:-ghcr.io/jovlinger/thermo-onboard:latest}"
ARG1="${1:-}"

log() { echo "[$(date +%H:%M:%S)] $*"; }

# --- Prep: ensure Docker is installed and running ---
prep_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        log "Docker not found. Installing..."
        curl -fsSL https://get.docker.com -o /tmp/get-docker.sh
        sh /tmp/get-docker.sh
        rm -f /tmp/get-docker.sh
        log "Adding $USER to docker group (log out and back in for group to take effect)"
        sudo usermod -aG docker "$USER" 2>/dev/null || true
    fi
    if ! docker info >/dev/null 2>&1; then
        log "Starting Docker daemon..."
        sudo systemctl start docker 2>/dev/null || sudo service docker start 2>/dev/null || true
    fi
}

log "Starting run-onboard.sh"

# Run prep when --prep or when docker unavailable
if [ "$ARG1" = "--prep" ] || ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    log "Preparing Docker..."
    prep_docker
fi

# Use sudo docker if user not yet in docker group (e.g. right after install)
DOCKER="docker"
docker info >/dev/null 2>&1 || DOCKER="sudo docker"
log "Using: $DOCKER"

# Source local env (e.g. CR_PAT for GHCR, DMZ_URL for twoway) before pull
log "Loading env..."
[ -f ~/.local.sh ] && . ~/.local.sh

# Login to GHCR if CR_PAT set (for private images)
if [ -n "${CR_PAT:-}" ]; then
    log "Logging in to GHCR..."
    echo "$CR_PAT" | $DOCKER login ghcr.io -u jovlinger --password-stdin 2>/dev/null || true
fi

# On armhf (32-bit Pi OS), pull arm/v7 explicitly; otherwise may get wrong arch
PLATFORM=""
case "$(uname -m)" in armv7l|armv6l) PLATFORM="--platform linux/arm/v7";; esac
[ -n "$PLATFORM" ] && log "Platform: armhf (linux/arm/v7)"

PULL="$ARG1"
if [ "$PULL" = "--prep" ]; then PULL=""; fi

if [ "$PULL" = "--pull" ] || ! $DOCKER image inspect "$IMAGE" >/dev/null 2>&1; then
    log "Pulling $IMAGE (plain progress for remote SSH)..."
    $DOCKER pull --progress=plain $PLATFORM "$IMAGE"
    log "Pull complete."
else
    log "Image present, skipping pull."
fi

log "Removing old container (if any)..."
$DOCKER rm -f thermo-onboard 2>/dev/null || true

# Rolling log buffer: persists on host for post-reboot diagnosis (Docker creates dir if missing)
LOG_DIR="${THERMO_LOG_DIR:-/var/log/thermo-onboard}"

# Device flags: I2C (temp/humidity), LIRC (IR TX; RX optional)
DEVICES="--device /dev/i2c-1 --device /dev/lirc0"
[ -c /dev/lirc1 ] 2>/dev/null && DEVICES="$DEVICES --device /dev/lirc1"

log "Starting container..."
# Host network: onboard listens on Pi's IP:5000, reachable by DMZ
# LOG_PATH: rolling buffer (500 lines) for post-reboot diagnosis
# DMZ_URL: full URL to DMZ (global IP or domain). E.g. http://203.0.113.42:5000
[ -n "${DMZ_URL:-}" ] && log "DMZ_URL=$DMZ_URL"
$DOCKER run -d --restart unless-stopped \
    --name thermo-onboard \
    --network host \
    -v "$LOG_DIR:/var/log/thermo-onboard" \
    $DEVICES \
    -e PORT=5000 \
    -e LOG_PATH=/var/log/thermo-onboard/onboard.log \
    -e LOG_MAX_LINES=500 \
    ${DMZ_URL:+-e "DMZ_URL=$DMZ_URL"} \
    "$IMAGE"

log "Started thermo-onboard. Logs: $DOCKER logs -f thermo-onboard"
log "Persistent log buffer: $LOG_DIR/onboard.log (tail -f for rolling view)"
