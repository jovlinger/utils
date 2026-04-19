# Thermo config env files

Use **committed templates** (`*.env.sample`) and **private copies** (`*.env`) ignored by git (`thermo/.gitignore`).

## Selecting a file: `THERMO_ENV_FILE`

Set **`THERMO_ENV_FILE`** to a path **relative to `thermo/`** or an absolute path. The shared loader is `source-thermo-env.sh` (sourced by deploy scripts and `thermo/test/Makefile`).

We use **`THERMO_ENV_FILE`**, not `ENV`, because **`ENV` is already the app runtime** (Flask / tests: `DOCKERTEST`, `TEST`, …).

Examples:

```bash
# Host pytest (defaults in repo)
export THERMO_ENV_FILE=config/test.env.sample
make -C thermo/test test-local

# Deploy onboard stack on this Pi (copy template first)
cp thermo/config/deploy.env.sample thermo/config/kitchen.env
# edit kitchen.env — DMZ_HOST, ZONE_NAME in install/.env, etc.
export THERMO_ENV_FILE=config/kitchen.env
./thermo/onboard/install/deploy-compose.sh
```

Multiple units in one house: keep **`config/kitchen.env`**, **`config/den.env`**, each with its own `DMZ_HOST` / overrides; pick the file when deploying that Pi.

## Templates

| File | Purpose |
|------|---------|
| **`test.env.sample`** | Localhost URLs for `thermo/test` e2e (ports 5001 / 5002). |
| **`deploy.env.sample`** | Example DMZ scheme/host/port for production-style deploy. |

Copy to `config/<name>.env` (ignored), adjust, then `export THERMO_ENV_FILE=config/<name>.env`.

## Manual sourcing

```bash
cd /path/to/utils
export THERMO_ROOT="$PWD/thermo"
export THERMO_ENV_FILE=config/kitchen.env
set -a
. "$THERMO_ROOT/config/source-thermo-env.sh"
set +a
```
