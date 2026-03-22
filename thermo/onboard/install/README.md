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

## DMZ URL (twoway sync) — blessed approach

The onboard `twoway` process syncs environment data to the DMZ. On standalone Pi (no docker-compose), the default `http://dmz:5000` does not resolve on **host** network. Configure the DMZ **base URL** on the Pi, then **recreate** the container so Docker injects `DMZ_URL` (editing `~/.local.sh` alone does not change a running container).

Use the base URL only (e.g. `http://host:5000`); [run.sh](../run.sh) appends `/zone/zoneymczoneface/sensors`.

### 1. Persist `DMZ_URL` in `~/.local.sh`

```bash
# Example: DMZ on the same LAN (replace with your DMZ host/IP)
export DMZ_URL="http://192.168.88.200:5000"
# Other examples: public IP, or HTTPS hostname
# export DMZ_URL="http://203.0.113.42:5000"
# export DMZ_URL="https://dmz.example.com"
```

If you change an existing value, remove or edit the old `DMZ_URL` line so only one definition remains.

### 2. Ensure `run-onboard.sh` passes `DMZ_URL` into Docker

[run-onboard.sh](run-onboard.sh) must source `~/.local.sh` and pass `-e DMZ_URL=...` to `docker run`. If the Pi’s checkout is old (script has no `DMZ_URL` lines), update from git:

```bash
ssh johan@pizero.local 'cd ~/github.com/jovlinger/utils && git pull && cd thermo/onboard/install && ./run-onboard.sh'
```

Otherwise recreate the container from the install directory (pull optional):

```bash
ssh johan@pizero.local 'cd ~/github.com/jovlinger/utils/thermo/onboard/install && ./run-onboard.sh'
# or: ./run-onboard.sh --pull
```

### 3. Verify

```bash
ssh johan@pizero.local 'docker inspect thermo-onboard --format "{{range .Config.Env}}{{println .}}{{end}}" | grep DMZ_URL'
ssh johan@pizero.local 'docker logs --tail 20 thermo-onboard'
```

`twoway` startup logs should show your DMZ URL in the argv list (not `http://dmz:5000/...`).

### Reboot behavior (no `onboard.service` required)

`run-onboard.sh` uses `docker run --restart unless-stopped`. After you recreate the container once with `DMZ_URL`, the Docker daemon will bring **`thermo-onboard`** back on reboot with the **same** env (including `DMZ_URL`). That is independent of [Auto-Start (systemd)](#auto-start-systemd); systemd is optional for a fixed install path and explicit `ExecStart` on every boot.

## Post-Reboot Diagnosis

A rotating app log is written to the host for post-reboot diagnosis:

```bash
# View container logs (live)
ssh johan@pizero.local 'docker logs -f thermo-onboard'

# View persistent buffer (survives container restart)
ssh johan@pizero.local 'tail -200 /var/log/thermo-onboard/onboard.log'
```

Override log location: `THERMO_LOG_DIR=~/thermo-logs ./run-onboard.sh`

Rotation defaults (same strategy as DMZ):

- file rotate at 1 MiB (`LOG_FILELIMIT=1048576`)
- rotated-files total cap 2 MiB (`LOG_TOTALLIMIT=2097152`)

## Management Endpoint

Onboard exposes `/manage`:

- `GET /manage`: internal runtime state (pid, log level, queue sizes, fake sensor state)
- `POST /manage`: control actions for diagnostics/fault injection

`POST` body examples:

```json
{"action":"inject_log","level":"INFO","message":"hello"}
{"action":"set_log_level","level":"DEBUG"}
{"action":"raise","message":"simulate exception"}
{"action":"assert","message":"simulate assertion"}
{"action":"fatal","code":99}
{"action":"reset"}
```

Safety:
- Require `X-Manage-Token` header matching `MANAGE_TOKEN` env var.
