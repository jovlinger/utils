# Onboard Install (Pi Zero 2 W)

Auto-start the thermo onboard container on Raspberry Pi Zero 2 W. Uses GHCR for image hosting.

## Prerequisites

- Raspberry Pi Zero 2 W (arm64)
- Docker installed (or let the script install it)
- I2C enabled: `sudo raspi-config` → Interfacing Options → I2C
- LIRC for IR: `/dev/lirc0` (TX) must exist (ANAVI IR pHAT)

## Quick Start

```bash
# Copy install scripts to the Pi
scp -r thermo/onboard/install pi@pizero.local:~/

# On the Pi (installs Docker if missing, then pull & run)
cd install
chmod +x run-onboard.sh
./run-onboard.sh
# Or explicitly: ./run-onboard.sh --prep
```

## GHCR Token (for private images)

Your GHCR login is in `~/.docker/config.json` with `"credsStore": "desktop"` — credentials live in macOS Keychain (Docker Desktop), not in `~/.local`.

**On the Pi** (if the image is private):

1. Create a GitHub PAT with `read:packages` scope
2. `echo $PAT | docker login ghcr.io -u jovlinger --password-stdin`
3. Or store in `~/.config/thermo/ghcr-token` and source before run

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
