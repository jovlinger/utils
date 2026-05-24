# Thermo config env files

Use **committed room env files** (`*.env`) for deploy specs and **templates** (`*.env.sample`) for examples. Put secrets and private local overrides under `thermo/priv/`.

## Selecting a file: `THERMO_ENV_FILE`

Set **`THERMO_ENV_FILE`** to a path **relative to `thermo/`** or an absolute path. The shared loader is `source-thermo-env.sh` (sourced by deploy scripts and `thermo/test/Makefile`).

We use **`THERMO_ENV_FILE`**, not `ENV`, because **`ENV` is already the app runtime** (Flask / tests: `DOCKERTEST`, `TEST`, ...).

Examples:

```bash
# Host pytest (defaults in repo)
export THERMO_ENV_FILE=config/test.env.sample
make -C thermo/test test-local

# Deploy an onboard room target (copy template first)
cp thermo/config/kitchen.env.sample thermo/config/kitchen.env
# edit kitchen.env: host, ZONE_NAME, behavior choices, etc.
export THERMO_ENV_FILE=config/kitchen.env
make -C thermo/onboard deploy
```

Multiple units in one house: keep **`config/kitchen.env`**, **`config/bedroom.env`**, each with its own `ZONE_NAME`, deploy backend, destination host, and runtime overrides; pick the file when deploying that room.

## Onboard deployments

Each onboard env file names one deployed unit and selects the hardware and behaviors:

```sh
ZONE_NAME=kitchen
ONBOARD_DEPLOY_BACKEND=pizero2w
ONBOARD_DEPLOY_HOST=pizerokitchen.local
ONBOARD_DEPLOY_USER=johan
ONBOARD_DEPLOY_REPO=/home/johan/github.com/jovlinger/utils
ONBOARD_DEPLOY_ENV_FILE=config/kitchen.env
ONBOARD_HARDWARE_PROFILE=pi_zero_2w_htu21d_ir
ONBOARD_SEND_BEHAVIOR=ir_daikin
ONBOARD_REPORT_BEHAVIOR=sensor_readings
SENSOR_DRIVER=htu21d
IR_TRANSPORT=lirc
IR_DEVICE=/dev/lirc0
```

`ZONE_NAME` is the human-readable deployment key used by DMZ and UI. It must be unique for the deployment and must be a single URL path segment, so use names like `kitchen`, `den`, or `bedroom_1`.

`ONBOARD_DEPLOY_BACKEND` selects the host-type deployment implementation under `thermo/onboard/hardware/<backend>/install/`. For example, `pizero2w` deploys by SSHing to `ONBOARD_DEPLOY_HOST`, pulling git in `ONBOARD_DEPLOY_REPO`, then running `make -C thermo/onboard deploy` on the target with `ONBOARD_DEPLOY_ENV_FILE`.

The initial supported hardware profile is `pi_zero_2w_htu21d_ir`: Raspberry Pi Zero 2 W, HTU21D temperature/humidity sensor on I2C, and a LIRC IR sender. Its supported behaviors are `ir_daikin` for sending commands and `sensor_readings` for reporting environment readings.

Example room destinations:

```sh
# kitchen.env
ZONE_NAME=kitchen
ONBOARD_DEPLOY_BACKEND=pizero2w
ONBOARD_DEPLOY_HOST=pizerokitchen.local
ONBOARD_DEPLOY_ENV_FILE=config/kitchen.env

# bedroom.env
ZONE_NAME=bedroom
ONBOARD_DEPLOY_BACKEND=pizero2w
ONBOARD_DEPLOY_HOST=bedroompc.local
ONBOARD_DEPLOY_ENV_FILE=config/bedroom.env

# tvroom.env
ZONE_NAME=tvroom
ONBOARD_DEPLOY_BACKEND=esp32
# esp32 deploy is not implemented yet; it should own the USB-C flash flow.
```

## Templates

| File | Purpose |
|------|---------|
| **`test.env.sample`** | Localhost URLs for `thermo/test` e2e (ports 5001 / 5002). |
| **`deploy.env.sample`** | Example DMZ scheme/host/port for production-style deploy. |
| **`kitchen.env.sample`** | Concrete first onboard deployment: kitchen Pi Zero 2 W + HTU21D + Daikin IR. |

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
