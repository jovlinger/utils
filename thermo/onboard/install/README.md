# Install scripts (Pi)

**Primary documentation:** [../README.md](../README.md) — two GHCR images, `docker-compose.yml`, `deploy-compose.sh`, systemd, troubleshooting.

## Quick commands

```bash
export THERMO_ENV_FILE=config/kitchen.env   # or config/den.env — path relative to thermo/
cd ~/github.com/jovlinger/utils
git pull
cd thermo/onboard/install
./deploy-compose.sh
```

First-time: copy a template from [`../../config/deploy.env.sample`](../../config/deploy.env.sample) to `../../config/<name>.env` (gitignored), set `THERMO_ENV_FILE` as above, then deploy. Copy `env.example` to `.env` only for compose overrides (`ZONE_NAME`, …), or set variables in `~/.local.sh`.

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Stack: app + twoway; optional **connectivity-watchdog** via profile `thermo-watchdog` (needs current GHCR twoway image) |
| `deploy-compose.sh` | `docker compose pull` + `up -d` (requires `THERMO_ENV_FILE`; sources `thermo/config/source-thermo-env.sh` then `~/.local.sh`) |
| `deploy.sh` | `git pull` (repo root) then `deploy-compose.sh` |
| `install-systemd.sh` | Installs `thermo-onboard.service` for boot |
| `env.example` | Template for `.env` |
| `run-onboard.sh` | **Deprecated** — old single-container runner |
| `onboard.service` | **Deprecated** — old systemd unit |

## GHCR

Images: `ghcr.io/jovlinger/thermo-onboard-app` and `ghcr.io/jovlinger/thermo-onboard-twoway`. Private packages need `CR_PAT` in `~/.local.sh` before pull.
