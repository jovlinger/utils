# Thermo onboard (Pi)

Two **separate** container images on **GHCR**:


| Image                                     | Role                                                       |
| ----------------------------------------- | ---------------------------------------------------------- |
| `ghcr.io/jovlinger/thermo-onboard-app`    | Flask API (`app.py`), static UI (`thermo/ui`), I2C/LIRC |
| `ghcr.io/jovlinger/thermo-onboard-twoway` | DMZ ↔ onboard sync (`twoway.py`)                           |


**Viewing images in the browser after `make push`:** there is no separate “ghcr.io gallery” URL per image. GitHub hosts the UI. The predictable links are:

- App package: [github.com/jovlinger/utils/pkgs/container/thermo-onboard-app](https://github.com/jovlinger/utils/pkgs/container/thermo-onboard-app)
- Twoway package: [github.com/jovlinger/utils/pkgs/container/thermo-onboard-twoway](https://github.com/jovlinger/utils/pkgs/container/thermo-onboard-twoway)

If a link 404s (e.g. package not linked to this repo), open [your packages](https://github.com/jovlinger?tab=packages), or go to the **utils** repo → **Packages** in the right sidebar (or **Code** → find **Packages** under the repo name on the new UI).

They are started together with **Docker Compose** (`install/docker-compose.yml`): **host networking**, **CPU limits** via `deploy.resources` (memory cgroup limits are not set — they are often unsupported on Raspberry Pi OS and only produce warnings), bounded **ulimits** for open files, and **no Docker json log growth** (`logging: driver: none`) because each process logs **only** through `**run-with-stdout-logged.py`** into bind-mounted files under `**/var/log/thermo-onboard/**`.

## Log files (host)

After deploy, on the Pi:


| File              | Contents             |
| ----------------- | -------------------- |
| `onboard-app.log` | Flask app (`app.py`) |
| `onboard-ui.log`  | UI server            |
| `twoway.log`      | Twoway sync          |
| `connectivity-watchdog.log` | Optional **connectivity-watchdog** service (see below) |

**Connectivity watchdog (optional):** the `connectivity-watchdog` service uses the same image as twoway and needs `docker-entrypoint-watchdog.sh` inside that image. Until GHCR `thermo-onboard-twoway:latest` is rebuilt from the current repo, leave **`COMPOSE_PROFILES`** unset so `deploy-compose.sh` only starts app + twoway. After you `make push` (or CI builds the image), add `COMPOSE_PROFILES=thermo-watchdog` to `install/.env` or `~/.local.sh` and redeploy to start the watchdog.

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
2. **Choose a config env file** (see [`thermo/config/README.md`](../config/README.md)): copy `thermo/config/kitchen.env.sample` to `thermo/config/kitchen.env` (or create `den.env` from the same template; `*.env` is gitignored). Set:
  ```bash
   export THERMO_ENV_FILE=config/kitchen.env
  ```
   Use a distinct file per onboard unit. Set a unique `ZONE_NAME`, then select `ONBOARD_HARDWARE_PROFILE`, `ONBOARD_SEND_BEHAVIOR`, and `ONBOARD_REPORT_BEHAVIOR` in that file.
3. **Run the deploy script** (pulls images and starts the stack):
  ```bash
   cd thermo/onboard/install
   chmod +x deploy-compose.sh install-systemd.sh
   ./deploy-compose.sh
  ```
4. **Optional: systemd** so reboot brings the stack up:
  ```bash
   mkdir -p ~/.config/thermo-onboard
   echo 'THERMO_ENV_FILE=config/kitchen.env' > ~/.config/thermo-onboard/environment
   sudo ./install-systemd.sh
   sudo systemctl enable --now thermo-onboard
  ```
   The unit reads `~/.config/thermo-onboard/environment` for `THERMO_ENV_FILE`, then runs `deploy-compose.sh` from `install/`. Adjust paths in `thermo-onboard.service.in` only if your checkout layout differs; `install-systemd.sh` substitutes `@@INSTALL@@`, `@@USER@@`, and `@@HOME@@`.

**Each upgrade:** `git pull` → `./deploy-compose.sh` from `install/` (same as step 3). Systemd will **not** auto-pull new images until you run deploy again or restart the unit after a pull — for upgrades, run `./deploy-compose.sh` manually or re-run the service after `git pull`.

## Resource limits

Compose sets **CPU** per service via `deploy.resources.limits`. **Memory** is not capped in Compose (cgroup memory is unreliable on many Pi kernels); keep footprint in check with log rotation (`LOG_*LIMIT`) and host `ulimits`. Tune `deploy.resources` and `ulimits` in `install/docker-compose.yml` for your Pi. Add `pids` limits if your Compose version supports them under `deploy.resources.limits`.

## Troubleshooting

- `**docker compose` not found:** Install Docker Compose v2 (`docker compose version`). On Raspberry Pi OS, Docker’s official install usually includes it.
- `**permission denied` talking to Docker socket:** `sudo usermod -aG docker "$USER"` and re-login.
- **Twoway errors / DMZ unreachable:** Check the file named by `THERMO_ENV_FILE` (`DMZ_HOST` / `DMZ_PORT`) or override `DMZ_URL`. Check `twoway.log` and `curl` the DMZ from the Pi.
- **Onboard HTTP not listening:** Check `onboard-app.log`, `docker compose ps`, and `curl -sS http://127.0.0.1:5000/` (host network).
- `**/dev/lirc0` or `/dev/i2c-1` missing:** Enable I2C / LIRC; comment out unused `devices:` lines in `docker-compose.yml` only if you accept reduced functionality.
- `**docker compose up` fails on `vcgencmd` or `/dev/vchiq`:** Those are for Pi SoC temperature and throttle flags on the **connectivity-watchdog** service. Remove the `vcgencmd` bind and `devices:` entry for that service when developing on a non-Pi host.
- **Compose ignores `deploy.resources`:** On some older Compose versions, limits apply only in Swarm. Upgrade Docker/Compose, or add equivalent `docker run` flags via `docker compose` override (see Docker docs).
- **No lines in `docker logs`:** Expected — logging driver is `none`. Use the files under `/var/log/thermo-onboard/`.
- **Stale images:** Run `./deploy-compose.sh` after `git pull`; it always `**docker compose pull`** before `**up**`.
- By far the biggest issue is intermittent wifi issues with the pizero 2W (revision unknown).  Apparently there is a known brcmfmac issue. This may be the cause. (but we won't know tonight since the pizero went off-air again)
  > the brcmfmac firmware crashes hard and leaves the SDIO bus in a dead state — the whole system becomes unresponsive and only a power cycle helps. The 60-second disassociation cycle (a confirmed open firmware bug as of March 2026) runs continuously in the background, and after enough cycles the firmware state machine corrupts. The multi-AP same-SSID setup is an amplifying factor — brcmfmac's autonomous roaming is a documented crash path. PSU undervoltage during a WiFi TX burst can trigger the same crash.

## Development

- **Local venv:** `run.sh` without Docker still runs twoway + UI + app for development (see `run.sh`).
- **Build images locally:** From `thermo/onboard/`, `make build` / `make push` (requires `CR_PAT`).
- **CI:** `.github/workflows/thermo-onboard.yml` builds and pushes both images on changes under `thermo/onboard/` or `bin/` (log wrapper + `mock_cmd` snapshots). If the job fails with **403** on `ghcr.io` (often `HEAD request … Forbidden` during push), open [your packages](https://github.com/jovlinger?tab=packages), select **`thermo-onboard-app`** and **`thermo-onboard-twoway`** → **Package settings** → **Manage Actions access** → add **`jovlinger/utils`** with **Write**. For org-owned packages, also confirm org **Actions** settings allow publishing packages.

## Legacy

The single image `ghcr.io/jovlinger/thermo-onboard` (monolithic Dockerfile) is **replaced** by the two images above. Older `install/run-onboard.sh` + `onboard.service` flow is deprecated in favor of `deploy-compose.sh` + `thermo-onboard.service`.

More install notes: [install/README.md](install/README.md).