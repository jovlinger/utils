# Agent Notes -- Pi Zero 2 W onboard

GHCR images, logs, tmpfs, and human ops: [`README.md`](README.md).

## Deploy checklist

Prerequisites: Docker + Compose v2, user in group `docker`, I2C + LIRC as needed,
optional GHCR token in `~/.local.sh` if images are private. Zone private key on
the target: `thermo/priv/zone/priv.pem`.

```bash
# Prefer zone Makefiles / deploy dispatcher
make -C thermo/onboard deploy ZONE=kitchen

# Optional: already on the Pi
ONBOARD_DEPLOY_LOCAL=1 make -C thermo/onboard deploy ZONE=kitchen
```

Each upgrade: run deploy again (systemd does not auto-pull new images).

Env selection: [`../../../config/AGENTS.md`](../../../config/AGENTS.md).

## Troubleshooting (agent-facing)

- `docker compose` missing: install Compose v2 (`docker compose version`).
- Permission denied on Docker socket: `usermod -aG docker` and re-login.
- Twoway / DMZ: check `THERMO_ENV_FILE` (`DMZ_HOST` / `DMZ_PORT`) or `DMZ_URL`;
  read `twoway.log`; curl DMZ from the Pi.
- HTTP not listening: `onboard-app.log`, `docker compose ps`,
  `curl -sS http://127.0.0.1:5000/` (host network).
- No lines in `docker logs`: expected (`logging: driver: none`); use
  `/var/log/thermo-onboard/` bind mounts.
- Stale images: redeploy so the Pi backend pulls before `up`.
- GHCR push **403** from CI: package settings -> Manage Actions access -> add
  `jovlinger/utils` with Write (see README Development section).
