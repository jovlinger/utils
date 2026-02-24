# Onboard requirements

This document describes the current onboard behavior and the requirements for
interfacing with the ANAVI IR pHAT hardware: the IR transceiver and the
temperature/humidity sensor.

## Scope

The onboard service:
- Exposes a simple HTTP API for environment data and IR commands.
- Reads temperature/humidity from the ANAVI IR pHAT (HTU21D via I2C).
- Transmits and receives IR to control a Daikin heat-pump head unit.

## Existing behavior (current repo state)

From `onboard/app.py` and `onboard/anavilib.py`:
- Flask app serves on port `5000` by default.
- `GET /environment` reads the HTU21D over I2C and returns
  `temperature_centigrade` and `humidity_percent`.
- `GET /daikin` returns an in-memory map of commands.
- `POST /daikin` stores an incoming command but does not transmit IR yet.
- `HTU21D` access is implemented via `smbus` on I2C bus `1`.
- In test environments (`ENV=TEST` or `ENV=DOCKERTEST`), I2C is mocked by
  `smbus_fake`.

## Hardware interfaces

### I2C (temperature/humidity)

- I2C bus: `1` (`/dev/i2c-1`).
- Sensor: HTU21D, address `0x40`.
- Commands: `0xE3` temperature, `0xE5` humidity, `0xFE` reset.

### IR transceiver (ANAVI IR pHAT)

- `/dev/lirc0` = TX (GPIO 18).
- `/dev/lirc1` = RX (GPIO 17).
- Carrier: 38 kHz (handled by hardware/LIRC).
- The RX device cannot measure carrier frequency (hardware limitation).
- **Critical:** The default LIRC receiver timeout is **5000 µs (5 ms)**.
  Daikin inter-frame gaps are ~30 ms, so the default fragments every
  transmission. Must set `--timeout 200000` (200 ms) when receiving.

## Daikin IR protocol — ARC452A9

Target remote: **ARC452A9**. All facts below are confirmed by captures
(`scribble/captures/`) unless noted otherwise.

### Encoding

- Pulse-distance, 38 kHz carrier, LSB-first bytes.
- Start mark: pulse ~3490 µs, space ~1750 µs.
- Bit 0: pulse ~420 µs, space ~420 µs.
- Bit 1: pulse ~420 µs, space ~1300 µs.
- Checksum: last byte of each frame = `sum(preceding bytes) & 0xFF`.

### Frame structure

Each button press sends **2 frames** separated by a ~30 ms gap:

| Frame | Bytes | Content |
|-------|-------|---------|
| F1 | 8 | Fixed: `11 da 27 f0 00 00 00 02` |
| F3 | 19 | Full unit state (mode, temp, fan, etc.) |

No Frame 2 (`0x42`) is sent. This differs from the ARC470A1 (blafois)
which sends 3 frames (F1 + F2 + F3).

F1 is identical in every ARC452A9 capture: `11 da 27 f0 00 00 00 02`.
Byte 3 = `0xf0` (vs `0x00` in blafois) identifies the ARC452A9 variant.
Comfort mode may be encoded in F1 byte 6 bit 4, but we have no captures
with comfort enabled.

### F3 byte map (19 bytes, 0-indexed)

| Byte | Field | Decode | Status |
|------|-------|--------|--------|
| 0-2 | Header | `11 da 27` | ✅ confirmed |
| 3 | Fixed | `0x00` | ✅ confirmed |
| 4 | Fixed | `0x00` | ✅ confirmed |
| 5[7:4] | Mode | 0=AUTO 2=DRY 3=COOL 4=HEAT 6=FAN | ✅ confirmed HEAT, FAN |
| 5[0] | Power | 0=OFF, 1=ON | ✅ confirmed |
| 5[1] | Timer OFF enable | per blafois | ❓ no captures with timers |
| 5[2] | Timer ON enable | per blafois | ❓ no captures with timers |
| 5[3] | Unknown | always 0 in captures | ❓ blafois says "always 1" for ARC470A1 |
| 6 | Temp × 2 | e.g. 0x2c = 22 °C | ✅ confirmed 22 °C, 25 °C |
| 7 | Unknown | always `0x00` | ❓ |
| 8[7:4] | Fan speed | 3-7 = 1/5-5/5, A=Auto, B=Silent | ✅ confirmed 5/5, Silent |
| 8[3:0] | Swing (vertical) | 0=off, F=on per blafois | ❓ only seen off |
| 9 | Unknown | always `0x00` | ❓ horizontal swing? |
| 0x0a | Timer ON low | 12-bit minutes per blafois | ❓ always 0x00 |
| 0x0b | Timer hi/lo | shared by ON and OFF timers | ❓ always 0x00 |
| 0x0c | Timer OFF high | 12-bit minutes per blafois | ❓ always 0x00 |
| 0x0d | Powerful | bit 0 per blafois | ❌ "powerful" press showed 0x00 |
| 0x0e | Unknown | always `0x00` | ❓ |
| 0x0f | Fixed? | always `0xc0` (blafois: `0xc1`) | ❓ ARC452A9 difference |
| 0x10 | Econo | bit 2 per blafois | ❓ always 0x00, no captures |
| 0x11 | Unknown | always `0x00` | ❓ |
| 0x12 | Checksum | sum(0x00..0x11) & 0xFF | ✅ confirmed |

Legend: ✅ = confirmed by ARC452A9 captures. ❓ = from blafois (ARC470A1),
not yet confirmed. ❌ = blafois mapping appears wrong for this remote.

### Known discrepancies vs blafois (ARC470A1)

1. **Frame count:** ARC452A9 sends 2 frames (F1+F3). ARC470A1 sends 3 (F1+F2+F3).
2. **F1 byte 3:** `0xf0` (ARC452A9) vs `0x00` (ARC470A1).
3. **F3 byte 5 bit 1:** Always 0 in captures. Blafois says "always 1" for ARC470A1.
4. **F3 byte 0x0f:** `0xc0` (ARC452A9) vs `0xc1` (blafois).
5. **Powerful bit:** Pressing "powerful" on ARC452A9 did not set byte 0x0d.
   The bit may be at a different location, or the capture was taken at the
   wrong moment. Needs targeted captures.

### Captures needed to resolve unknowns

| Test | Purpose | Bytes to watch |
|------|---------|----------------|
| Swing on/off | Confirm vertical swing bit | byte 8 low nibble |
| Swing + examine H/V | Horizontal swing? | byte 9 |
| Powerful on vs off | Find the powerful bit | diff all bytes |
| Econo on vs off | Find the econo bit | byte 0x10 |
| Comfort on vs off | Find comfort encoding | F1 byte 6, or F3 |
| Set ON timer (e.g. 2h) | Timer encoding + enable bits | byte 5[1:3], 0x0a-0x0c |
| Set OFF timer | Timer encoding + enable bits | byte 5[1:3], 0x0a-0x0c |
| Set clock/time on remote | Does clock data appear? | bytes 0x0a-0x0c or elsewhere |
| Mode AUTO/DRY/COOL | Confirm remaining mode nibbles | byte 5 |

Each test: capture baseline, change ONE setting, capture again, diff.
Use `ir_capture.py -t 200000` for reliable full-frame capture.

### daikin-send.py known issues

The send code (`scribble/daikin-send.py`) was written from the blafois spec
before we had captures. Known issues vs ARC452A9 reality:

1. **byte5 power encoding:** Send uses `0x09` (bit0 + bit3) for ON.
   Captures show `0x01` (bit0 only). bit3 is not used on ARC452A9.
2. **F1 header:** Send uses `11 da 27 00 c5`. ARC452A9 uses `11 da 27 f0 00`.
3. **Frame 2:** Send includes F2 (`11 da 27 00 42 ...`). ARC452A9 omits it.
4. **byte 0x0f:** Send uses `0xc1`. ARC452A9 captures show `0xc0`.

These must be fixed before sending to the head unit.

### Timing and receiver configuration

| Parameter | Value | Source |
|-----------|-------|--------|
| Start mark pulse | ~3490 µs | captures |
| Start mark space | ~1750 µs | captures |
| Bit pulse | ~420 µs | captures |
| Bit 0 space | ~420 µs | captures |
| Bit 1 space | ~1300 µs | captures |
| Inter-frame gap | ~30 ms | captures (29974 µs) |
| LIRC receiver timeout | 200000 µs | required (default 5000 fragments) |
| Full transmission | ~50 ms | F1 + gap + F3 |

### Tools

| Tool | Purpose |
|------|---------|
| `scribble/ir_capture.py` | Low-level capture (mode2 format, verbatim, no decoding) |
| `scribble/daikin-recv.py` | Capture + decode (live or from log via `--parse-log`) |
| `scribble/daikin-send.py` | Generate and send IR (needs fixes, see above) |

Capture files: `scribble/captures/` — plain text `.log` files, one per run.

### Reference links

- [blafois/Daikin-IR-Reverse](https://github.com/blafois/Daikin-IR-Reverse) — ARC470A1 protocol (primary reference, differs from ARC452A9)
- [rdlab Daikin IR protocol](https://rdlab.cdmt.vn/experience/daikin-ir-protocol) — ARC433A46 timing and layout
- [IRremoteESP8266](https://github.com/crankyoldgit/IRremoteESP8266) — ARC433 timing constants (ARC452A9 not in supported list)

## Ports and endpoints

- Onboard Flask API: `5000` (configurable via `PORT` env var).
- I2C: `/dev/i2c-1` (bus 1).
- IR TX: `/dev/lirc0` (GPIO 18).
- IR RX: `/dev/lirc1` (GPIO 17).

## Open questions / TODOs

- Fix `daikin-send.py` for ARC452A9 (see known issues above).
- Capture the remaining unknowns (swing, powerful, econo, timers, clock).
- Define the command schema that `POST /daikin` should accept.
- Validate: send a generated command and confirm the head unit responds.
