# Onboard requirements

This document describes the current onboard behavior and the requirements for
interfacing with the ANAVI IR pHAT hardware: the IR transceiver and the
temperature/humidity sensor.

## Scope

The onboard service:
- Exposes a simple HTTP API for environment data and IR commands.
- Reads temperature/humidity from the ANAVI IR pHAT (HTU21D via I2C).
- Will transmit and receive IR to control a Daikin heat-pump head unit.

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

Known from the current implementation:
- I2C bus: `1` (i.e., `/dev/i2c-1` on Raspberry Pi).
- Sensor: HTU21D.
- I2C address: `0x40`.
- Commands used:
  - `0xE3` for temperature.
  - `0xE5` for humidity.
  - `0xFE` for reset.

Requirements:
- Keep the current smbus-based read path as the default.
- Preserve the `smbus_fake` fallback for unit tests and container tests.
- Add retries and clearer error messages if I2C reads fail.

### IR transceiver (TX/RX)

Not yet implemented in the codebase.

Requirements:
- IR transmit: generate a modulated carrier (likely 38kHz, confirm).
- IR receive: sample demodulated pulses for learning/verification.
- Define precise GPIO pins once confirmed from ANAVI IR pHAT docs/schematics.
  - TODO: document the exact GPIO BCM pins for TX/RX and any enable pins.

## Ports and endpoints

Network ports:
- Onboard Flask API: `5000` (configurable via `PORT` env var).

Hardware ports:
- I2C: `/dev/i2c-1` (bus 1).
- GPIO: TBD for IR TX/RX (must be confirmed from ANAVI IR pHAT docs).

## ANAVI library customization

We currently use a shim (`onboard/anavilib.py`) that copies the HTU21D logic.
Requirements for the final approach:
- Keep the dependency surface small (avoid unmaintained libraries).
- Provide a stable `HTU21D` interface with:
  - explicit bus selection,
  - injection of a fake bus for tests,
  - error handling that explains how to fix missing I2C packages.
- Introduce a new `IRTransceiver` interface with `send()` and `receive()`.
- Avoid hidden globals to make testing straightforward.

## Direct bus access vs. ANAVI libraries

Decision (current recommendation):
- Temperature/humidity: keep direct I2C access via `smbus` (already working).
- IR TX/RX: use direct GPIO access via a stable library (`pigpio` or `lirc`),
  rather than relying on the ANAVI examples.

Rationale:
- The ANAVI examples are simple and often copy-pasted; direct bus access is
  easier to audit and test.
- For IR, precise timing matters; `pigpio`/`lirc` are purpose-built for this.

## Daikin IR code generation

We need a reproducible way to generate IR commands for Daikin head units.

**Note:** Daikin IR pulses are reported to contain unexpected pauses that confuse
many learning remotes. Relying on raw capture/replay with a learning remote is
therefore a last resort; generating protocol-correct frames is preferred.

### Plan (hierarchical checklist)

- **THEN** 1. Obtain Daikin protocol and timing
  - **OR** 1a. Use a reverse‑engineered spec (e.g. blafois/Daikin-IR-Reverse)
  - **OR** 1b. Capture from original remote and decode (receiver on pHAT, store raw pulse widths)
- **THEN** 2. Implement decoder (receive path)
  - **OR** 2a. Decode live from IR receiver (e.g. `scribble/daikin-recv.py`)
  - **OR** 2b. Decode from stored raw capture files
- **THEN** 3. Implement encoder (send path)
  - **OR** 3a. Generate frames from structured inputs and send (e.g. `scribble/daikin-send.py`)
  - **OR** 3b. Replay stored raw captures as stopgap
- **THEN** 4. Validate
  - Replay or send generated commands and confirm head unit responds.
  - Optionally compare generated vs captured byte frames.

### Facts (for implementation)

- **Remote naming:** Daikin remote models are named **ARC** + model (e.g. ARC452A9, ARC470A1). Our target remote for capture/decoder work is **ARC452A9**.
- **Hardware (Pi Zero 2W + ANAVI IR pHAT):** `/dev/lirc0` = TX (GPIO 18), `/dev/lirc1` = RX (GPIO 17). Carrier is 38kHz (handled by hardware when using LIRC/ir-ctl).
- **Daikin protocol (from blafois/Daikin-IR-Reverse, remote ARC470A1):** Each keypress sends **3 frames**. Frames 1 and 2 are 8 bytes each, frame 3 is 19 bytes. Frames are separated by long gaps (~30 ms+). Encoding is **pulse distance**: HIGH ~430–452 µs, LOW short = bit 0 (~419–420 µs), LOW long = bit 1 (~1286–1320 µs). Bytes are LSB first. **Checksum:** last byte of each frame = sum of all previous bytes in that frame, masked with 0xFF.
- **Frame 1 (code 0xc5):** Header `11 da 27 00`, then `c5`, then byte 6 = comfort (0x00 or 0x10), byte 7 = checksum.
- **Frame 2 (code 0x42):** Fixed `11 da 27 00 42 00 00 54`.
- **Frame 3 (code 0x00):** Header `11 da 27 00 00`; then byte 5 = mode/on-off/timer, byte 6 = temperature×2, byte 8 = fan/swing, bytes 0a–0c = timer delay, byte 0d = powerful, byte 0x10 = econo (low nibble); last byte = checksum. Mode nibble: 0=AUTO, 2=DRY, 3=COOL, 4=HEAT, 6=FAN. On/off/timer bits in byte 5: bit 0 = always 1, bit 1 = timer OFF, bit 2 = timer ON, bit 3 = power (1=On, 0=Off). Temperature: Celsius × 2 in hex. Fan nibble: 3–7 = fan 1–5, 0xA = Auto, 0xB = Silent. Swing: 0 = off, 0xF = on (in fan byte low nibble).
- **Other remotes/variants:** Different Daikin models use different frame lengths or layouts (e.g. ARC433A46: 8+8+19; ARC423A5: 7+13; some docs use different bit order or checksum). The blafois layout may not match every unit; decoder/sender may need tuning per remote/head unit.
- **Research links (uncertain match to our units):** [blafois/Daikin-IR-Reverse](https://github.com/blafois/Daikin-IR-Reverse) (START HERE), [OpenMQTTGateway Daikin dump](https://community.openmqttgateway.com/t/my-daikin-ac-irrecvdumpv2-work-corretly-but-omg-no/415), [Reddit re remote codes](https://www.reddit.com/r/hvacadvice/comments/15z4aly/remote_code_for_daikin_ac_unit/), [rdlab Daikin IR protocol](https://rdlab.cdmt.vn/experience/daikin-ir-protocol) (ARC433A46 timing and layout).
- **IRremoteESP8266 Daikin (ARC433) timing (for comparison):** `kDaikinHdrMark` 3650 µs, `kDaikinHdrSpace` 1623 µs, `kDaikinBitMark` 428 µs, `kDaikinZeroSpace` 428 µs, `kDaikinOneSpace` 1280 µs, `kDaikinGap` 29000 µs. ARC452A9 is **not** in their supported model list; use as reference only.
- **Captures (scribble/captures/):** Each run of `daikin-recv` opens one new capture file (by date); only units captured in that run are written (no load of previous data). `daikin_recv_YYYY-MM-DD.pkl` holds records with `timestamp`, `label`, `description`, `raw_lines`. Inspected capture: 27 bytes decoded; first three bytes `11 da 27` correct; then `f0 00...` vs expected `00 c5...`; frame IDs raw[4]/raw[12] are 0x00 instead of 0xC5/0x42. Space distribution 400–499 µs (zero) and 1200–1299 µs (one); start ~3497/1725 µs.
- **Why one click can become two units (blafois + Java):** One keypress sends one *transmission*: 3 frames with gaps between them. blafois’ Arduino “stops after a timeout” (one capture per press). Our daikin-send (and blafois Transmitter) send F1, then **30 ms gap**, F2, then **30 ms gap**, F3 (GAP_BETWEEN_FRAMES_US). The remote usually **repeats** that whole block 2–3 times per press; the gap between repeats is typically tens of ms (not seconds). So in IR time one click is one contiguous burst (~100–200 ms). We split into “units” only when we see **no data on ir-ctl stdout for PAUSE_SEC (2 s)**. So we get two units only if (1) **spurious first**: a tiny glitch (e.g. one 12‑char line) is read, then **2 s** with no more data, so we yield that as unit 1; the real press comes later and becomes unit 2; or (2) **stdout buffering**: the kernel/ir-ctl delivers the same keypress in two chunks with a long delay (>2 s) between them. So the split is not because the protocol has a 2 s gap; it’s either noise yielding early or buffering. To reduce spurious units: don’t yield “tiny” units (e.g. one line and total length &lt; 100 chars)—keep buffering until real data or timeout. To reduce buffering splits: increase PAUSE_SEC (e.g. 5 s) so we wait longer before ending a unit (at the cost of slower prompt return).
- **Comparison with blafois/Daikin-IR-Reverse (ARC470A1):** In agreement: (1) **Timing** — blafois measures HIGH 424–500 µs, LOW short (0) 396–436 µs, LOW long (1) 1264–1300 µs; our thresholds (pulse 250–650, space0 300–550, space1 1000–1600) contain these. (2) **Checksum** — blafois: sum of all but last byte, mask 0xFF, equals last byte; our `checksum_ok()` matches. (3) **Header** — `11 da 27 00`; we decode that. (4) **Frame layout** — blafois Frame 1 code 0xc5, Frame 2 code 0x42, Frame 3 code 0x00; our decoder expects raw[4]=0xC5, raw[12]=0x42 and decodes F3 from bytes 16–34. (5) **LSB first** — both. So our implementation matches blafois. The ARC452A9 capture yields valid header and F1 checksum but byte 3/4 differ (f0 00 vs 00 c5), so ARC452A9 may use different frame identifiers or a variant layout; blafois does not list ARC452A9.

## Open questions / TODOs

- Confirm the exact ANAVI IR pHAT GPIO pins for IR TX/RX.
- Confirm IR carrier frequency used by the Daikin head unit.
- Decide between `pigpio` and `lirc` based on availability in the target OS.
- Define the command schema that `POST /daikin` should accept.

