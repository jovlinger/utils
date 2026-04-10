# Install scripts (Pi)

**Primary documentation:** [../README.md](../README.md) — two GHCR images, `docker-compose.yml`, `deploy-compose.sh`, systemd, troubleshooting.

## Quick commands

```bash
cd ~/github.com/jovlinger/utils
git pull
cd thermo/onboard/install
./deploy-compose.sh
```

First-time: copy `env.example` to `.env` and set `DMZ_URL`, or set `DMZ_URL` in `~/.local.sh`.

## Files

| File | Purpose |
|------|---------|
| `docker-compose.yml` | Stack: app + twoway + connectivity-watchdog (`vcgencmd`/`vchiq` for Pi hw metrics) |
| `deploy-compose.sh` | `docker compose pull` + `up -d` (sources `~/.local.sh`) |
| `deploy.sh` | `git pull` (repo root) then `deploy-compose.sh` |
| `install-systemd.sh` | Installs `thermo-onboard.service` for boot |
| `env.example` | Template for `.env` |
| `run-onboard.sh` | **Deprecated** — old single-container runner |
| `onboard.service` | **Deprecated** — old systemd unit |

## GHCR

Images: `ghcr.io/jovlinger/thermo-onboard-app` and `ghcr.io/jovlinger/thermo-onboard-twoway`. Private packages need `CR_PAT` in `~/.local.sh` before pull.
