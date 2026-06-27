---
name: hw-electrical-debug
description: >-
  Guides HAT electrical bring-up using Thermo hardware debug commands (GPIO
  read/set, IR promiscuous RX). Use when debugging HAT continuity, solder
  bridges, IR TX/RX, GPIO levels, USB CDC debug serial, pizero2w hwdebug.py,
  or thermo/onboard/hardware/*/debug.rs firmware debug.
---

# Hardware Electrical Debug

Use the shared line-oriented debug protocol to verify printed HAT copper and
module wiring before trusting sensors or IR in the main poll loop.

Protocol implementation: `thermo/onboard/hardware/pico2w/src/debug.rs` (also
linked from `esp32s3/src/lib.rs`). Pi Zero host CLI:
`thermo/onboard/hardware/pizero2w/hwdebug.py`.

## When To Use What

| Backend | Debug interface | GPIO HAT tests | IR RX stream |
| --- | --- | --- | --- |
| Pico2W | USB CDC serial (`Thermo Pico2W Debug`) | yes | yes (`ir promisc`) |
| ESP32-S3 | same command set (parser ready; wire serial when firmware ships) | yes (planned) | yes (planned) |
| Pi Zero 2W | `hwdebug.py` on the Pi | no (LIRC pHAT, not GPIO HAT) | yes via `/dev/lirc1` |

Network `GET /healthz` and `GET /logs` on port 5000 are for firmware health,
not GPIO continuity. Prefer USB serial on Pico2W during HAT bring-up.

## Connect (Pico2W)

1. Flash/deploy `ledw_status` firmware.
2. Unplug/replug without BOOTSEL.
3. Open the CDC device (baud is ignored):

```bash
ls /dev/cu.usbmodem*
screen /dev/cu.usbmodemXXXX 115200
```

Banner: `Thermo Pico2W USB debug connected (type help)`.

Agent: run `ls /dev/cu.usbmodem*` and open serial yourself when the user asks
for electrical debug; do not ask them to paste readouts unless the device is
unreachable from this environment.

## Command Reference

All backends share these commands (case insensitive):

```text
help
pins
gpio set <pin> hi|lo
gpio read <pin>
ir promisc on|off
```

Response shapes:

```text
OK <message>
ERR <message>
gpio <pin> hi|lo          # read result
gpio <pin> set hi|lo      # set confirmation
ir edge <micros> us hi|lo # promiscuous IR RX (stdout)
```

Run `pins` first. It lists the active zone `DeviceConfig` GPIO map, not every
Pico header pin.

## Default HAT GPIO Maps

Confirm with `pins` after deploy; values follow zone env / compile-time config.

**Pico2W** (`pico2w/hat/pico-side.vox`):

| Net | Name | GPIO |
| --- | --- | --- |
| AHT20 SCL | aht20_scl | GP27 |
| AHT20 SDA | aht20_sda | GP28 |
| IR TX module OUT | ir_tx | GP10 |
| IR RX module OUT | ir_rx | GP13 |

**ESP32-S3** (plan defaults in `esp32s3/src/config.rs`):

| Net | Name | GPIO |
| --- | --- | --- |
| AHT20 SCL | aht20_scl | 36 |
| AHT20 SDA | aht20_sda | 35 |
| IR TX | ir_tx | 17 |
| IR RX | ir_rx | 6 |

Cross-check net names against the board `.vox` trace layer and
`electrical-debug` pin map before blaming firmware.

## Continuity Workflow (GPIO HAT)

Goal: prove each HAT signal reaches the MCU pin.

For each net in `pins`:

1. **Open circuit baseline** -- with nothing shorted:

```text
gpio read <pin>
```

Expect `lo` on inputs with pulldown or floating reads (SCL/SDA may read `hi`
from onboard/I2C pull-ups when the bus is idle).

2. **Short to 3V3** -- tell the user to jumper the HAT pad (or module pin) to
   3V3, then:

```text
gpio read <pin>
```

Expect `hi`. If still `lo`, trace is open or wrong GPIO.

3. **Short to GND** (optional) -- jumper pad to GND:

```text
gpio read <pin>
```

Expect `lo`. If `hi`, suspect a short to 3V3 or a stuck driver.

4. **Drive test** (output nets such as IR TX) -- force the pin:

```text
gpio set <pin> hi
gpio read <pin>
gpio set <pin> lo
gpio read <pin>
```

Use a meter or scope on the HAT pad; `read` confirms the MCU side.

Example I2C SCL check on Pico2W office HAT:

```text
pins
gpio read 27
# user shorts SCL pad to 3V3
gpio read 27
```

Work one net per iteration; update scratch notes in the `.vox` file if a route
is wrong.

### Pico2W pins to avoid driving

GP23, GP24, GP25, GP29 are CYW43 WiFi SPI. Do not use `gpio set` on them
during bring-up unless intentionally debugging WiFi wiring.

## IR TX / RX Workflow

Goal: confirm IR TX emits and IR RX sees edges.

1. Start promiscuous capture:

```text
ir promisc on
```

2. Trigger IR TX (another remote, `gpio set` on IR TX to toggle a test LED
   on the TX module if wired, or normal firmware IR send after WiFi is up).

3. Expect streaming lines:

```text
ir edge 1240 us hi
ir edge 560 us lo
...
```

4. Stop capture:

```text
ir promisc off
```

No edges usually means: wrong RX GPIO, RX module not powered, TX not firing,
or IR LED orientation.

## Pi Zero 2W (LIRC)

GPIO HAT commands are not supported. IR RX only:

```bash
# on the Pi (or in container with /dev/lirc1 passed through)
thermo/onboard/hardware/pizero2w/hwdebug.py
# or one-shot:
thermo/onboard/hardware/pizero2w/hwdebug.py pins
thermo/onboard/hardware/pizero2w/hwdebug.py ir promisc on
```

Env: `IR_DEVICE=/dev/lirc0` (TX), `IR_RX_DEVICE=/dev/lirc1` (RX).

## Agent Checklist

Copy and track during a bring-up session:

```text
Electrical debug progress:
- [ ] Open debug interface (USB serial or hwdebug.py)
- [ ] Run pins and record GPIO map
- [ ] Baseline gpio read for each HAT net
- [ ] 3V3 short test for each input net
- [ ] Optional GND short test
- [ ] IR promisc on; verify edges when TX fires
- [ ] Document pass/fail per net in chat or zone notes
```

If a net fails, read the board `.vox` trace layer and compare to
`thermo/onboard/hardware/SKILL.md` routing rules before changing firmware.

## Source Files

| File | Role |
| --- | --- |
| `pico2w/src/debug.rs` | Command parser and response helpers |
| `pico2w/src/bin/ledw_status.rs` | USB CDC task, GPIO steal, IR promisc poll |
| `pico2w/README.md` | USB serial bring-up |
| `pizero2w/hwdebug.py` | Pi Zero LIRC promisc CLI |
| `pico2w/hat/*.vox` | Expected nets and GPIO labels |
| `esp32s3/src/config.rs` | ESP32-S3 default GPIO map |
