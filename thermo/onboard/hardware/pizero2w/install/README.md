# Pi Zero 2 W Install Backend

**Primary documentation:** [../README.md](../README.md).

## Quick commands

```bash
make -C thermo/onboard deploy ZONE=kitchen
```

The top-level install scripts source `THERMO_ENV_FILE`, read `ONBOARD_DEPLOY_BACKEND`, and dispatch to `hardware/<backend>/install/`.
For Pi Zero 2 W deployments, the concrete compose and systemd files live in this directory.

| File | Purpose |
|------|---------|
| `deploy.sh` | Pi Zero 2 W backend used by `make deploy` |
| `deploy-compose.sh` | Local compose deploy helper |
| `install-systemd.sh` | Backend systemd installer |
| `run-onboard.sh` | Deprecated old single-container runner |
| `onboard.service` | Deprecated old systemd unit |

## GHCR

Images: `ghcr.io/jovlinger/thermo-onboard-app` and `ghcr.io/jovlinger/thermo-onboard-twoway`. Private packages need `CR_PAT` in `~/.local.sh` before pull.
