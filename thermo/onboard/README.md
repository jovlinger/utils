# Thermo onboard (Pi)

Two **separate** container images on **GHCR**:

| Image | Role |
|-------|------|
| `ghcr.io/jovlinger/thermo-onboard-app` | Flask API (`app.py`), static UI (`ui_server.py`), I2C/LIRC |
| `ghcr.io/jovlinger/thermo-onboard-twoway` | DMZ ↔ onboard sync (`twoway.py`) |

They are started together with **Docker Compose** (`install/docker-compose.yml`): **host networking**, **hard cgroup-style limits** (memory and CPU via `deploy.resources`), bounded **ulimits** for open files, and **no Docker json log growth** (`logging: driver: none`) because each process logs **only** through **`run-with-stdout-logged.py`** into bind-mounted files under **`/var/log/thermo-onboard/`**.

## Log files (host)

After deploy, on the Pi:

| File | Contents |
|------|----------|
| `onboard-app.log` | Flask app (`app.py`) |
| `onboard-ui.log` | UI server |
| `twoway.log` | Twoway sync |

Rotation is handled inside the container by `run-with-stdout-logged.py` (`LOG_FILELIMIT` / `LOG_TOTALLIMIT`, default 1 MiB file / 2 MiB rotated total per stream — same idea as before).

### Preferred for SD wear reduction: host tmpfs

To avoid SD card write wear, keep the existing bind mount path and mount the host log directory as `tmpfs`.

- Compose already bind-mounts `${THERMO_LOG_DIR:-/var/log/thermo-onboard}` into each container.
- Preferred setup: make `/var/log/thermo-onboard` a RAM-backed mount on the Pi.
- Tune `size=` based on free RAM and your retention target.

Example:

```bash
sudo mkdir -p /var/log/thermo-onboard
echo 'tmpfs /var/log/thermo-onboard tmpfs rw,nosuid,nodev,mode=0755,size=16m 0 0' | sudo tee -a /etc/fstab
sudo mount /var/log/thermo-onboard
```

If you prefer a different tmpfs path, set `THERMO_LOG_DIR` (in `install/.env` or `~/.local.sh`) to that path and ensure it exists at boot.

## Deploy on `pizero.local` (upgrade loop)

**Prerequisites:** Docker + Compose v2 plugin, user in group `docker`, I2C + LIRC devices as before, optional GHCR token in `~/.local.sh` if images are private.

1. **Clone/pull** the repo on the Pi (example path):

   ```bash
   cd ~/github.com/jovlinger/utils
   git pull
   ```

2. **Configure DMZ** (required for twoway):

   ```bash
   # ~/.local.sh — sourced by deploy-compose.sh
   export DMZ_URL="http://192.168.88.200:5000"
   ```

   Or copy `thermo/onboard/install/env.example` to `thermo/onboard/install/.env` and edit `DMZ_URL` there.

3. **Run the deploy script** (pulls images and starts the stack):

   ```bash
   cd thermo/onboard/install
   chmod +x deploy-compose.sh install-systemd.sh
   ./deploy-compose.sh
   ```

4. **Optional: systemd** so reboot brings the stack up:

   ```bash
   sudo ./install-systemd.sh
   sudo systemctl enable --now thermo-onboard
   ```

   The unit runs `deploy-compose.sh up` from `install/` and `deploy-compose.sh down` on stop. Adjust paths in `thermo-onboard.service.in` before install only if your checkout path differs; `install-systemd.sh` substitutes `@@INSTALL@@`, `@@USER@@`, and `@@HOME@@`.

**Each upgrade:** `git pull` → `./deploy-compose.sh` from `install/` (same as step 3). Systemd will **not** auto-pull new images until you run deploy again or restart the unit after a pull — for upgrades, run `./deploy-compose.sh` manually or re-run the service after `git pull`.

## Resource limits

Compose sets **memory** and **CPU** per service via `deploy.resources.limits` so the footprint stays bounded. If a container exceeds memory, the **OOM killer** stops it loudly (restart policy brings it back after you fix the cause). Tune `deploy.resources` and `ulimits` in `install/docker-compose.yml` for your Pi (512 MiB RAM total — leave headroom for the OS). Add `pids` limits if your Compose version supports them under `deploy.resources.limits`.

## Troubleshooting

- **`docker compose` not found:** Install Docker Compose v2 (`docker compose version`). On Raspberry Pi OS, Docker’s official install usually includes it.
- **`permission denied` talking to Docker socket:** `sudo usermod -aG docker "$USER"` and re-login.
- **Twoway errors / DMZ unreachable:** Set `DMZ_URL` to the **base** URL of the DMZ (e.g. `http://192.168.1.10:5000`). Check `twoway.log` and `curl` the DMZ from the Pi.
- **Onboard HTTP not listening:** Check `onboard-app.log`, `docker compose ps`, and `curl -sS http://127.0.0.1:5000/` (host network).
- **`/dev/lirc0` or `/dev/i2c-1` missing:** Enable I2C / LIRC; comment out unused `devices:` lines in `docker-compose.yml` only if you accept reduced functionality.
- **Compose ignores `deploy.resources`:** On some older Compose versions, limits apply only in Swarm. Upgrade Docker/Compose, or add equivalent `docker run` flags via `docker compose` override (see Docker docs).
- **No lines in `docker logs`:** Expected — logging driver is `none`. Use the files under `/var/log/thermo-onboard/`.
- **Stale images:** Run `./deploy-compose.sh` after `git pull`; it always **`docker compose pull`** before **`up`**.

## Development

- **Local venv:** `run.sh` without Docker still runs twoway + UI + app for development (see `run.sh`).
- **Build images locally:** From `thermo/onboard/`, `make build` / `make push` (requires `CR_PAT`).
- **CI:** `.github/workflows/thermo-onboard.yml` builds and pushes both images on changes under `thermo/onboard/`.

## Legacy

The single image `ghcr.io/jovlinger/thermo-onboard` (monolithic Dockerfile) is **replaced** by the two images above. Older `install/run-onboard.sh` + `onboard.service` flow is deprecated in favor of `deploy-compose.sh` + `thermo-onboard.service`.

More install notes: [install/README.md](install/README.md).
