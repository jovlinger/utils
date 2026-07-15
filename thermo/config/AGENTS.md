# Agent Notes -- thermo/config

Human field meanings and templates: [`README.md`](README.md).

## Selecting an env file

Set `THERMO_ENV_FILE` to a path **relative to `thermo/`** or an absolute path.
The shared loader is `source-thermo-env.sh` (sourced by deploy scripts and
`thermo/test/Makefile`).

Use **`THERMO_ENV_FILE`**, not `ENV` -- `ENV` is already the app runtime
(Flask / tests: `DOCKERTEST`, `TEST`, ...).

```bash
export THERMO_ENV_FILE=config/test.env.sample
make -C thermo/test test-local

make -C thermo/onboard/zones/kitchen deploy
```

Hardware-local shortcuts:

```bash
cd thermo/onboard/hardware/pico2w
./deploy.sh office-pico2w.env   # board must be in BOOTSEL

cd thermo/onboard/hardware/pizero2w
./deploy.sh kitchen.env         # SSH when remote; local when on the host
```

Secrets and private overrides live under `thermo/priv/` -- never commit them.
