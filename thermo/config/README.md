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

Hardware-local deploy shortcuts are also available:

```bash
cd thermo/onboard/hardware/pico2w
./deploy.sh office-pico2w.env
./deploy.sh office-pico2w.env --deploy=true

cd thermo/onboard/hardware/pizero2w
./deploy.sh kitchen.env
./deploy.sh kitchen.env --deploy=true
```

Without `--deploy=true`, both shortcuts run in check mode. With
`--deploy=true`, the Pico2W shortcut flashes and requires the board in BOOTSEL
mode. The Pi Zero 2 W shortcut reads `ONBOARD_DEPLOY_HOST`; it SSHes when run
from another machine and deploys locally when already on the target host.

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
ONBOARD_SEND_BEHAVIOR=ir_heatpump
ONBOARD_IR_PROTOCOL=daikin_arc452a9
ONBOARD_REPORT_BEHAVIOR=sensor_readings
SENSOR_DRIVER=htu21d
IR_TRANSPORT=lirc
IR_DEVICE=/dev/lirc0
```

`ZONE_NAME` is the human-readable deployment key used by DMZ and UI. It must be unique for the deployment and must be a single URL path segment, so use names like `kitchen`, `den`, or `bedroom_1`.

`ZONE_PRIVATE_KEY_PATH` points at the ignored private key used for zone
authentication, usually `$THERMO_ROOT/priv/zone/priv.pem`. Pico2W manifests
also set `PICO2W_PRIV_ENV` to the ignored per-room private env file, such as
`$THERMO_ROOT/priv/pico2w/office.env`; that file holds `PICO2W_WIFI_PASSWORD`
and any private overrides.

`ONBOARD_DEPLOY_BACKEND` selects the host-type deployment implementation under `thermo/onboard/hardware/<backend>/install/`. For example, `pizero2w` deploys by SSHing to `ONBOARD_DEPLOY_HOST`, pulling git in `ONBOARD_DEPLOY_REPO`, then running `make -C thermo/onboard deploy` on the target with `ONBOARD_DEPLOY_ENV_FILE`.

The initial supported hardware profile is `pi_zero_2w_htu21d_ir`: Raspberry Pi Zero 2 W, HTU21D temperature/humidity sensor on I2C, and a LIRC IR sender. Pico2W targets use `pico2w_aht20_ir`.

Verified Pico2W baseline: AHT20 on I2C0 (`SDA` GP4, `SCL` GP5) at address
`0x38`, IR TX on GP14, optional IR RX on GP15, and modules powered from
`3V3_OUT` unless a module-specific voltage check says otherwise. Use this as
the template for Pico room configs; change only the room identity and
`ONBOARD_IR_PROTOCOL` unless hardware needs a deliberate tweak.

`ONBOARD_SEND_BEHAVIOR=ir_heatpump` selects the generic heat-pump IR sender. `ONBOARD_IR_PROTOCOL` selects the actual AC dialect:

- `daikin_arc452a9`: derived local Daikin ARC452A9 dialect.
- `midea_classic`: published Midea classic 48-bit protocol, for Office captures.
- `haier_yrw02`: published Haier YR-W02 112-bit protocol, for Bedroom captures.

The legacy `ONBOARD_SEND_BEHAVIOR=ir_daikin` still maps to `daikin_arc452a9`.

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
| ---- | ------- |
| **`test.env.sample`** | Localhost URLs for `thermo/test` e2e (ports 5001 / 5002). |
| **`deploy.env.sample`** | Example DMZ scheme/host/port for production-style deploy. |
| **`kitchen.env.sample`** | Concrete first onboard deployment: kitchen Pi Zero 2 W + HTU21D + Daikin IR. |
| **`kitchen-pico2w.env`** | Kitchen Pico2W deployment: AHT20 sensor, Pico GPIO IR, Rust firmware. |
| **`office-pico2w.env`** | Office Pico2W deployment: AHT20 sensor, Pico GPIO IR, Midea protocol, Rust firmware. |
| **`bedroom-pico2w.env`** | Bedroom Pico2W deployment: AHT20 sensor, Pico GPIO IR, Haier protocol, Rust firmware. |

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
