# Onboard Install (Pi Zero 2 W)

Auto-start the thermo onboard container on Raspberry Pi Zero 2 W. Uses GHCR for image hosting.

## Prerequisites

- Raspberry Pi Zero 2 W (arm64 or armhf/32-bit)
- Docker installed (or let the script install it)
- I2C enabled: `sudo raspi-config` → Interfacing Options → I2C
- LIRC for IR: `/dev/lirc0` (TX) must exist (ANAVI IR pHAT)

## Quick Start

```bash
# Option A: Copy install scripts to the Pi
scp -r thermo/onboard/install pi@pizero.local:~/thermo-onboard-install
ssh pi@pizero.local 'cd ~/thermo-onboard-install && chmod +x run-onboard.sh && ./run-onboard.sh --pull'

# Option B: Use repo on Pi (git pull first; if install was copied via scp, remove conflicts)
ssh pi@pizero.local 'cd ~/github.com/jovlinger/utils && git clean -fd thermo/onboard/install/ 2>/dev/null; git pull && cd thermo/onboard/install && ./run-onboard.sh --pull'
```

## GHCR Token (for private images)

Your GHCR login is in `~/.docker/config.json` with `"credsStore": "desktop"` — credentials live in macOS Keychain (Docker Desktop), not in `~/.local`.

**On the Pi** (if the image is private):

1. Create a GitHub PAT with `read:packages` scope
2. Add to `~/.local.sh`: `export CR_PAT=ghp_...` (script sources this before pull)
3. Or: `echo $PAT | docker login ghcr.io -u jovlinger --password-stdin` before run

**Public images**: Make the package public at https://github.com/users/jovlinger/packages — then no login needed on the Pi.

## Auto-Start (systemd)

```bash
# Copy script to a fixed location
sudo cp run-onboard.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/run-onboard.sh

# Install service
sudo cp onboard.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable onboard
sudo systemctl start onboard
```

## Image Source

- **GHCR**: `ghcr.io/jovlinger/thermo-onboard:latest` (built by GitHub Actions on push to main)
- **Local build & push**: from `thermo/onboard/` run `make build` and `make push` (requires `CR_PAT`)

Override image: `ONBOARD_IMAGE=ghcr.io/jovlinger/thermo-onboard:mytag ./run-onboard.sh`

**Platform**: On armhf (32-bit Pi OS), the script pulls `--platform linux/arm/v7` automatically.

## DMZ URL (twoway sync)

The onboard `twoway` process syncs environment data to the DMZ. On standalone Pi (no docker-compose), the default `http://dmz:5000` does not resolve. Set the full DMZ URL in `~/.local.sh`:

```bash
# DMZ can be a global IP, domain, or local hostname
export DMZ_URL="http://203.0.113.42:5000"
# or: export DMZ_URL="https://dmz.example.com"
```

Use the base URL only (e.g. `http://host:5000`); run.sh appends `/zone/zoneymczoneface/sensors`.

## Post-Reboot Diagnosis

A rolling log buffer (500 lines) is written to the host for post-reboot diagnosis:

```bash
# View container logs (live)
ssh johan@pizero.local 'docker logs -f thermo-onboard'

# View persistent buffer (survives container restart)
ssh johan@pizero.local 'tail -200 /var/log/thermo-onboard/onboard.log'
```

Override log location: `THERMO_LOG_DIR=~/thermo-logs ./run-onboard.sh`
