# Thermo onboard Pico2W

Rust target for the Pico2W thermostat controller.

The firmware binary `ledw_status` runs the fused onboard controller loop:

- `pico2w_aht20_ir` hardware profile.
- AHT20 on software I2C (SDA GP28, SCL GP27) with fallback to 21.0 C / 50.0 %
  when the sensor is missing and `SENSOR_BOOT_REQUIRED=0`.
- Signed HTTP `POST /zone/<zone>/sensors` to the DMZ long-poll endpoint.
- Command freshness comparison matching the existing DMZ protocol.
- Midea IR transmit on GP10 for strictly newer returned commands.
- Status LED events: one pulse when a DMZ poll starts, two pulses before
  IR send, three pulses during startup/config, and four pulses for error paths.

The physical status LED is the Pico2W onboard LED labeled `LEDW`, driven by the
CYW43 WiFi chip. Because LEDW is single-color, the firmware renders semantic
status as blink patterns: 1 pulse for poll-start happy path, 2 for IR send,
3 for startup/config, and 4 for errors.

A successful long-poll response with no command, or with an old command, is still
green/3 pulses. Blue/2 pulses is only for a newer command that the firmware is
about to send over IR.

The firmware exposes `GET /healthz` and `GET /logs` on the same default onboard
app port as Pi Zero, `5000`, after WiFi and DHCP are ready. `GET /healthz`
returns the Pi Zero health contract shape with Pico-specific details under a
`pico` object. There is no Pico filesystem log. The in-memory firmware log keeps
64 entries and returns up to 32 entries in newest-first order.

## Default Bring-Up: USB Serial First

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

Use the kitchen Pico2W config:

```bash
export THERMO_ENV_FILE=config/kitchen-pico2w.env
make -C thermo/onboard ONBOARD_BUILD_BACKEND=pico2w build
```

The backend also supports the shared onboard deploy dispatcher:

```bash
make -C thermo/onboard deploy ZONE=kitchen
```

Deploy builds and checks the firmware, then copies `PICO2W_UF2_PATH` to
`PICO2W_UF2_VOLUME`. The board must be mounted in BOOTSEL mode before deploy.

The firmware reads compile-time environment variables:

- `PICO2W_WIFI_SSID` or `WIFI_SSID`
- `PICO2W_WIFI_PASSWORD` or `WIFI_PASSWORD`
- `PICO2W_ZONE_PRIVATE_KEY_B64` or `ZONE_PRIVATE_KEY`
- `PICO2W_POST_TIMEOUT_SECS` for the DMZ long-poll timeout, default `600`

The deploy script also sources `thermo/priv/pico2w/<zone>.env` after the
committed room config. For `office`, put private values in
`thermo/priv/pico2w/office.env`; keep `ZONE_PRIVATE_KEY_PATH` pointed at the
existing `thermo/priv/zone/priv.pem`. The deploy script converts that PEM file
to `PICO2W_ZONE_PRIVATE_KEY_B64` for the firmware build.

The firmware intentionally blinks red forever when private values are missing,
because it cannot perform the real DMZ poll.

## Office Midea IR Reference

The Office capture matches the Coolix / Midea24-style byte-complement protocol,
not IRremoteESP8266's native `IRMideaAC` checksum protocol. Useful references:

- IRremoteESP8266 `ir_Coolix`: byte plus inverse encoding, 4.4 ms header, 560 us
  mark, 1.6 ms / 560 us spaces, and about a 5.2 ms packet gap:
  <https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Coolix.cpp>
- IRremoteESP8266 Midea24 note: a 48-bit NEC-like form with alternate inverted
  bytes, carrying 24 bits of real data:
  <https://github.com/crankyoldgit/IRremoteESP8266/blob/master/src/ir_Midea.cpp>
- Older standalone Midea encoder with the same `B2 xx yy` plus complement
  packet shape:
  <https://github.com/sheinz/esp-midea-ir/blob/master/midea-ir.c>

Current Office evidence: each command sends the complement-paired state packet
twice, then a third 48-bit `D5 ...` packet after the same roughly 5.2 ms gap.
For example, power-on captured as `B2 4D 9F 60 60 9F`,
`B2 4D 9F 60 60 9F`, then `D5 28 20 01 00 1E`.

Useful direct commands:

```bash
make -C thermo/onboard/hardware/pico2w build
make -C thermo/onboard/hardware/pico2w firmware-check
make -C thermo/onboard/hardware/pico2w firmware-build
PICO2W_TARGET=thumbv6m-none-eabi make -C thermo/onboard/hardware/pico2w firmware-check
```
