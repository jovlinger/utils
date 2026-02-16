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

Requirements and approach:
1. Capture reference codes from the original remote:
   - Use an IR receiver on the pHAT to record raw pulse timings.
   - Store captures in a raw format (e.g., JSON with pulse widths).
2. Determine the protocol and payload structure:
   - Identify header, bit encoding, and checksum fields.
   - Confirm carrier frequency (likely 38kHz).
3. Build an encoder that can generate commands from structured inputs:
   - Inputs: mode, target temperature, fan speed, swing, power, etc.
   - Output: pulse timings for the IR LED transmitter.
4. Validate:
   - Replay raw captures and confirm the head unit responds.
   - Compare generated commands to captured commands.

Notes:
- If protocol decoding is too slow initially, we can ship using raw replays as
  a stopgap, then replace with a proper encoder.

## Open questions / TODOs

- Confirm the exact ANAVI IR pHAT GPIO pins for IR TX/RX.
- Confirm IR carrier frequency used by the Daikin head unit.
- Decide between `pigpio` and `lirc` based on availability in the target OS.
- Define the command schema that `POST /daikin` should accept.

