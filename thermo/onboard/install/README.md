# Install dispatchers

**Primary documentation:** [../README.md](../README.md).

## Quick commands

```bash
THERMO_ENV_FILE=config/kitchen.env make -C thermo/onboard deploy
```

The top-level install scripts source `THERMO_ENV_FILE`, read `ONBOARD_DEPLOY_BACKEND`, and dispatch to `../hardware/<backend>/install/`.
For Pi Zero 2 W deployments, the concrete compose and systemd files live in `../hardware/pizero2w/install/`.

| File | Purpose |
|------|---------|
| `deploy.sh` | Common dispatcher used by `make deploy` |
| `deploy-compose.sh` | Compatibility wrapper for local backend compose deploys |
| `install-systemd.sh` | Compatibility wrapper for the backend systemd installer |
| `run-onboard.sh` | Deprecated old single-container runner |
| `onboard.service` | Deprecated old systemd unit |

## GHCR

Images: `ghcr.io/jovlinger/thermo-onboard-app` and `ghcr.io/jovlinger/thermo-onboard-twoway`. Private packages need `CR_PAT` in `~/.local.sh` before pull.
