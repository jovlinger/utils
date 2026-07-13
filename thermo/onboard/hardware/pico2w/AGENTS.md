# Agent Notes -- Pico2W onboard

Firmware behavior, LED semantics, healthz, and Office IR references:
[`README.md`](README.md).

## Default bring-up: USB serial first

Until WiFi association, DHCP, and `GET /healthz` are reliably verified, the
default development loop is USB CDC serial over the same cable used for UF2
flashing. Do not depend on DHCP leases or `/healthz` as the first debug signal:
those only exist after WiFi and DHCP are already working.

After flashing, unplug/replug the Pico2W without holding BOOTSEL, then open the
new serial device from the host:

```bash
ls /dev/cu.usbmodem*
screen /dev/cu.usbmodemXXXX 115200
```

The baud rate is ignored by USB CDC but keeps terminal tools happy. The firmware
advertises as `Thermo Pico2W Debug` and prints the rolling health log, including
early messages such as `wifi join start`, `wifi join failed`, `wifi wait dhcp`,
and `wifi and dhcp ready`.

Interactive hardware debug commands are available on the same serial port (type
`help`):

```text
help
pins
gpio set <pin> hi|lo
gpio read <pin>
ir promisc on|off
```

For HAT continuity, short a net to 3V3 (for example AHT20 SCL), then
`gpio read <pin>`. For IR receive testing, run `ir promisc on` and stream edge
lines while triggering IR TX.

Once serial shows `wifi and dhcp ready`, then verify the network path:

```bash
curl http://<pico-dhcp-ip>:5000/healthz
curl http://<pico-dhcp-ip>:5000/logs
```

## Deploy and build env

```bash
export THERMO_ENV_FILE=config/kitchen-pico2w.env
make -C thermo/onboard ONBOARD_BUILD_BACKEND=pico2w build
make -C thermo/onboard deploy ZONE=kitchen
```

Deploy builds and checks the firmware, then copies `PICO2W_UF2_PATH` to
`PICO2W_UF2_VOLUME`. The board must be mounted in BOOTSEL mode before deploy.

Compile-time env (and aliases):

- `PICO2W_WIFI_SSID` or `WIFI_SSID`
- `PICO2W_WIFI_PASSWORD` or `WIFI_PASSWORD`
- `PICO2W_ZONE_PRIVATE_KEY_B64` or `ZONE_PRIVATE_KEY`
- `PICO2W_POST_TIMEOUT_SECS` for the DMZ long-poll timeout, default `600`

The deploy script sources `thermo/priv/pico2w/<zone>.env` after the committed
room config. For `office`, put private values in `thermo/priv/pico2w/office.env`;
keep `ZONE_PRIVATE_KEY_PATH` pointed at `thermo/priv/zone/priv.pem`. The deploy
script converts that PEM to `PICO2W_ZONE_PRIVATE_KEY_B64` for the firmware build.

The firmware blinks red forever when private values are missing (cannot poll DMZ).

Direct hardware-tree targets:

```bash
make -C thermo/onboard/hardware/pico2w build
make -C thermo/onboard/hardware/pico2w firmware-check
make -C thermo/onboard/hardware/pico2w firmware-build
PICO2W_TARGET=thumbv6m-none-eabi make -C thermo/onboard/hardware/pico2w firmware-check
```
