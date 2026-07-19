# ESP32-S3 thermostat: OS-based firmware PLAN

This plan REPLACES the earlier bare Rust + ESP-IDF firmware attempt. That work
was moved to the untracked `OBSOLETE/` folder in this directory. Do not build on
it. Treat `OBSOLETE/` as read-only reference for exact protocol constants only.

The one true runtime spec lives in `thermo/onboard/spec/` (TSL JSON). This PLAN
is the ESP32-S3 translation guide; behavior must match TSL, not the other way
around.

Goal: run the same thermostat controller that the Pico2W runs, but on the
ESP32-S3, using a managed on-device runtime (Toit, or MicroPython as fallback)
instead of a compiled Rust/ESP-IDF image. The device must speak the existing DMZ
contract unchanged, so the DMZ server needs no edits.

The reader of this plan may be a smaller model. Follow the milestones in order.
Each milestone has concrete commands and a check that must pass before moving on.
Do not skip a check. If a check fails, stop and fix it before continuing.

--------------------------------------------------------------------------------

## Status and remaining steps (2026-07-10)

**Done**

- M0: Jaguar flashed on CH343 UART; device `esp32s3-office` at `192.168.88.73:9000`
- M1: `thermo-esp32s3` container (heartbeat only)
- M2: BYOB custom envelope with Monocypher Ed25519 C service
  (`envelope/` -> `out/firmware.envelope`, flashed); `jag run src/auth_kat.toit` PASS
- I2C remapped to GPIO8/GPIO9 (N16R8 octal PSRAM)

**Remaining (in order)**

1. **M3** -- `config.toit`, `protocol.toit`, NTP sync, signed long-poll POST to DMZ;
   verify `manage zones office` shows `backend: esp32s3`
2. **M4** -- `ir.toit`: RMT 38 kHz on GPIO17, Midea/Coolix frames, apply fresh commands
3. **M5** -- `sensor.toit`: AHT20 on GPIO8/9, fallback 1.0 C / 1.0 %
4. **M6** -- `led.toit` (optional): WS2812 status patterns
5. **M7** -- `health.toit` (optional): local `/healthz` and `/logs` on port 5000
6. **M8** -- `install/deploy.sh`, git-ignored `src/secrets.toit`, container autostart
   survives power cycle without laptop

TSL source of truth: `thermo/onboard/spec/`. Implementer guide:
`thermo/onboard/spec/AGENT_IMPLEMENT_TOIT.md`.

--------------------------------------------------------------------------------

## 0. Decision: Toit (primary) vs MicroPython (fallback)

Chosen primary runtime: **Toit / Jaguar.**

Why Toit:
- `jag flash` installs a VM once over serial; after that, code updates go over
  WiFi with `jag run` / `jag watch` in about two seconds. No reflash per edit.
- First-class ESP32 peripheral libraries in the standard SDK: `i2c` (AHT20),
  `rmt` (38 kHz IR carrier), `gpio`, plus packages for `http` and `ntp`.
- Structured language, tasks, and containers map cleanly onto the existing
  Pico2W module layout.

The one hard risk: **Ed25519 signing.** The DMZ auth requires an Ed25519
signature on every sensor POST (see section 4). Toit has NO Ed25519 in its
standard `crypto` library and NO published package for it as of this writing.
MicroPython, by contrast, has drop-in options (a pure-Python module, or a
prebuilt native `.mpy`). This is the single fact that could flip the decision.

Therefore Ed25519 was milestone M2 and a hard DECISION GATE:
- **PASSED 2026-07-09:** custom envelope C service + `auth_kat.toit` matches TSL vector.
  Continue on Toit for M3..M8.
- If a future board cannot run the custom envelope, STOP the Toit path and switch
  the whole firmware to MicroPython using Appendix B.

Do not try to run part on Toit and part on MicroPython. Pick one runtime for the
whole firmware based on the M2 outcome.

--------------------------------------------------------------------------------

## 1. Fixed hardware and zone facts (office)

Target board: ESP32-S3 DevKitC-1 compatible, module marked `S3-N16R8`
(16 MB flash, 8 MB octal PSRAM). The octal-PSRAM variant matters for MicroPython
firmware selection (Appendix B); Toit's prebuilt image handles it.

Office zone values come from `thermo/onboard/zones/office/zone.env` and
`thermo/priv/esp32s3/office.env`. Do not hardcode secrets in tracked files.

| Setting | Value |
| --- | --- |
| Zone name | `office` |
| DMZ scheme / host / port | `http` / `jovlinger.duckdns.org` / `5000` |
| Hardware profile | `esp32s3_aht20_ir` |
| Backend id | `esp32s3` |
| IR protocol | `midea24_coolix` |
| IR TX GPIO | `17` |
| IR RX GPIO | `6` (receive is optional; TX is required) |
| AHT20 I2C SDA GPIO | `8` |
| AHT20 I2C SCL GPIO | `9` |
| AHT20 I2C address | `0x38` |
| WiFi SSID | `lumiere` |
| WiFi password | in `thermo/priv/esp32s3/office.env` (`ESP32S3_WIFI_PASSWORD`) |
| Zone private key | `thermo/priv/zone/priv.pem` (Ed25519 PKCS8 PEM) |
| Onboard HTTP port | `5000` (for `/healthz`, `/logs`; optional, ship last) |
| Sensor required at boot | `0` (missing sensor -> use fallback, keep polling) |
| Status LED | onboard WS2812 RGB is addressable on GPIO38 (v1.1) or GPIO48 (v1.0). Optional; see M6. |

CORRECTED 2026-07-09: GPIO35/GPIO36 are NOT usable for I2C on this board.
Any ESP32-S3 module marked R8 or higher (octal PSRAM, which `S3-N16R8` is) wires
GPIO33-37 internally to the octal SPI flash/PSRAM bus; using them for anything
else corrupts flash/PSRAM access. Remapped AHT20 I2C to GPIO8 (SDA) / GPIO9
(SCL), both confirmed free on this module and already updated in `zone.env`
and the HAT trace notes.

--------------------------------------------------------------------------------

## 2. What we are porting (the "picopi port")

The reference implementation is the Pico2W firmware at
`thermo/onboard/hardware/pico2w/`. Its behavior (from
`pico2w/README.md` and `pico2w/src/`) is the spec. The single fused controller
binary there is `src/bin/ledw_status.rs`; the logic modules are:

| Pico2W Rust module | Responsibility | New Toit file (M-number) |
| --- | --- | --- |
| `src/config.rs` | zone/DMZ/pin config, env overrides | `src/config.toit` (M3) |
| `src/auth.rs` | SHA-256 of body, Ed25519 sign, headers | `src/auth.toit` (M2) |
| `src/protocol.rs` | build sensor POST JSON, parse command, freshness | `src/protocol.toit` (M3) |
| `src/sensors.rs` + `src/aht20.rs` | AHT20 read, fallback 1.0 C / 1.0 % | `src/sensor.toit` (M5) |
| `src/ir.rs` | Midea/Coolix frame build + timing | `src/ir.toit` (M4) |
| `src/health.rs` | `/healthz` and `/logs` JSON bodies | `src/health.toit` (M7, optional) |
| `src/led.rs` | status blink patterns | `src/led.toit` (M6, optional) |
| `src/main.rs` / `ledw_status.rs` | wifi, sntp, poll loop, wiring | `src/main.toit` (M3, M8) |

**This is not a compiler port.** Jaguar does not run WASM, Rust, or Python from
picopi or Pi Zero. See section 11 for the full HOW (bytecode model, what is
reused vs rewritten, and the MicroPython alternative).

The exact protocol constants below are copied from the working Pico2W and
`OBSOLETE/src/` code. Trust these constants over any prose elsewhere.

--------------------------------------------------------------------------------

## 3. DMZ contract (exact, do not change)

Request (long-poll):

```text
POST http://jovlinger.duckdns.org:5000/zone/office/sensors
Content-Type: application/json
X-Zone-Signature: <base64 Ed25519 signature, standard base64, NOT url-safe>
X-Zone-Timestamp: <unix epoch seconds, integer, as string>
X-Zone-Name: office
```

Signature is standard Base64 of the 64-byte Ed25519 signature (the working
Pico2W uses `base64ct::Base64`, i.e. standard alphabet with `+` `/` and `=`
padding; the encoded length is 88 chars). Match that exactly.

Signing payload (the bytes that get signed), with real newline bytes `\n`:

```text
POST\n/zone/office/sensors\n<epoch_seconds>\n<sha256_hex_of_body>
```

- `sha256_hex_of_body` is the lowercase hex SHA-256 digest of the exact request
  body bytes you send.
- `epoch_seconds` must be a real wall-clock time (NTP-synced). Before NTP sync
  completes, do NOT POST (the DMZ rejects stale/incorrect timestamps).

Request body JSON (build it exactly in this field order; the DMZ is tolerant of
order but match the Pico for parity). Temperatures use one decimal place:

```json
{"sensors":{"temp_centigrade":1.0,"humid_percent":1.0},
 "deployment":{"hardware_profile":"esp32s3_aht20_ir","zone_name":"office",
   "send_behavior":"ir_heatpump","report_behavior":"sensor_readings",
   "sensor_driver":"aht20","ir_transport":"esp32s3_rmt","ir_device":"gpio17",
   "ir_protocol":"midea24_coolix","backend":"esp32s3",
   "status_led_driver":"log_only"}}
```

Body rules:
- Cold start (before any IR command applied): OMIT the top-level `"command"`
  field entirely.
- After you apply an IR command, include `"command":<the command JSON object>`
  right after the `"sensors"` object on every subsequent POST. This is what the
  DMZ "strictly newer" gate reads back.
- Optional fields `"network"` and `"logs"` exist in the Pico body; add them only
  in M7. They are not required for a working poll.

Response and command freshness:
- Response is JSON. The command lives at `response.command` (may be `null`).
- Apply the command only if `response.command.created_dt` is a nonempty string
  that is lexicographically strictly greater than the last applied `created_dt`.
  Missing or empty `created_dt` means stale: do nothing.
- Persist the last applied `created_dt` in memory across poll iterations (start
  it as the empty string `""`).

Timeout: this is a LONG poll. Use a client read timeout of `600` seconds
(`ESP32S3_POST_TIMEOUT_SECS`). On network error: log, wait 5 s, retry.

--------------------------------------------------------------------------------

## 4. Ed25519 auth details (M2 target)

Input: the zone private key `thermo/priv/zone/priv.pem` (Ed25519, PKCS8 PEM).
The build/deploy step converts it to a base64 DER string on the host; on device
you need the raw 32-byte Ed25519 seed to construct the signing key.

Host-side key extraction (already done by the Pico deploy) yields the 32-byte
seed. For the new runtime, extract the seed once on the host and inject it as a
provisioning value (Toit: an asset or a config constant baked at deploy; do NOT
commit it). Steps to get the raw seed on the host:

```bash
# 32-byte Ed25519 seed as hex, from the PKCS8 PEM:
python3 - <<'PY'
from cryptography.hazmat.primitives import serialization
k = serialization.load_pem_private_key(open("thermo/priv/zone/priv.pem","rb").read(), None)
raw = k.private_bytes(serialization.Encoding.Raw,
                      serialization.PrivateFormat.Raw,
                      serialization.NoEncryption())
print(raw.hex())
PY
```

Signing algorithm (RFC 8032 Ed25519, pure, no context):
1. Compute `msg = payload_string.encode()` (section 3 payload).
2. `sig = Ed25519_sign(seed, msg)` -> 64 bytes.
3. `X-Zone-Signature = base64_standard(sig)`.

Known-answer test for M2 (MUST pass before continuing on Toit):
- Use seed of 32 zero bytes and message `b"abc"`, OR better, reproduce the
  Pico2W unit test in `pico2w/src/auth.rs` (`signs_request_headers`): key seed
  base64, method `POST`, path `/zone/test/sensors`, body `{}`, zone `test`,
  epoch `1700000000`, and assert the resulting signature base64 length is 88 and
  matches a value you cross-check with host `cryptography`/`pynacl`.
- Cross-check on the host: sign the identical payload with Python `pynacl` and
  compare base64 output byte-for-byte.

M2 approach on Toit (in priority order):
1. Search current packages first: `jag pkg sync && jag pkg search ed25519`
   and `jag pkg search crypto`. If a maintained Ed25519 signer exists, use it.
2. **BYOB via custom envelope C service (chosen path, 2026-07-09):** Toit has
   no dynamic C FFI. Bake Monocypher Ed25519 into a custom firmware envelope
   as an external service (`thermo.jovlinger/ed25519`), then call it from
   `src/auth.toit` via `system.external`. See `envelope/README.md`.
   Known-answer test: `jag run src/auth_kat.toit`.
3. If the custom envelope cannot be built/flashed, TRIGGER THE FALLBACK: go to
   Appendix B (MicroPython) and implement the whole firmware there instead.

Time budget for M2: custom-envelope build + KAT. Gate outcome decides M3..M8.

--------------------------------------------------------------------------------

## 5. IR protocol (M4 target) - Midea24 / Coolix

Transport: ESP32 RMT peripheral with 38 kHz carrier on GPIO17. In Toit use the
`rmt` standard library (it drives the same RMT hardware the DHT/HC-SR04 packages
use). Emit mark/space level pairs; enable carrier modulation at 38000 Hz on the
marks.

Timing constants (microseconds), from `pico2w/src/ir.rs`:

| Name | Value (us) |
| --- | --- |
| Header mark (`MIDEA_START_PULSE_US`) | 4500 |
| Header space (`MIDEA_START_SPACE_US`) | 4500 |
| Bit mark (`MIDEA_PULSE_US`) | 560 |
| Zero space (`MIDEA_SPACE_ZERO_US`) | 560 |
| One space (`MIDEA_SPACE_ONE_US`) | 1680 |
| Inter-packet gap (`MIDEA_GAP_US`) | 5200 |
| Carrier | 38000 Hz |

Frame structure (Coolix / Midea24 byte-complement form), from `pico2w/README.md`
"Office Midea IR Reference":
- Each state command sends the complement-paired state packet TWICE, then a
  third 48-bit `D5 ...` packet, each separated by the ~5200 us gap.
- Example capture for power-on: `B2 4D 9F 60 60 9F`, `B2 4D 9F 60 60 9F`, then
  `D5 28 20 01 00 1E`.
- The frame builder that turns a `HeatpumpCommand` (power, mode, temp, fan) into
  these bytes already exists in `OBSOLETE/src/ir.rs` / `pico2w/src/ir.rs`
  (`midea_classic_frames`). Port that byte-building logic verbatim; only the
  transmit layer (RMT vs Pico GPIO bit-bang) changes.

Bit encoding: for each byte, send bits MSB-first as: mark 560 us, then space
(1680 us for a 1, 560 us for a 0). Prefix each packet with the 4500/4500 header;
after the last bit of a packet send one final 560 us mark then the 5200 us gap.

Also support `command_type == "raw_ir_sequence"` (carrier 38000 Hz, signed
duration list, max 1024 entries, positive = mark, negative = space) as in
`pico2w/src/ir.rs`. This is lower priority than the Midea state frames.

M4 check: with an IR receiver or phone camera, confirm the LED pulses on TX.
Better: capture with the RX path or a logic analyzer and confirm header 4500/4500
and the two identical state packets plus the D5 packet.

--------------------------------------------------------------------------------

## 6. Milestones

Do these in order. Each has a check that must pass.

### M0. Toolchain + flashing (assume board accepts uploads)

Install Jaguar and flash the VM once over serial.

```bash
brew install toitlang/toit/jag      # macOS; see docs.toit.io for Linux
jag setup                           # downloads Toit SDK + firmware images
jag flash                           # pick serial port; enter WiFi SSID=lumiere + pw
```

Optionally store WiFi so you do not retype it:

```bash
jag config wifi set --wifi-ssid lumiere --wifi-password '<pw>'
```

Check M0: `jag monitor` shows the device booting and joining WiFi; `jag scan`
lists the device on the LAN. Host and device must share the network (Jaguar uses
UDP broadcast).

If `jag flash` cannot connect over serial, the board is not in download mode.
This is the same BOOT+RESET dance as esptool: hold BOOT, tap RESET, release BOOT,
then retry. See `OBSOLETE/` notes; do not spend more than a few tries.

### M1. Hello loop over WiFi

Create `src/main.toit` that prints a heartbeat every second. Run it live:

```bash
jag run src/main.toit          # one-shot
jag watch src/main.toit        # live reload on save
```

Check M1: edited output appears within ~2 s on `jag monitor` without reflashing.

### M2. Ed25519 signer (DECISION GATE - see section 4) -- DONE

`src/auth.toit` + `src/auth_kat.toit`; C service in `envelope/components/toit-ed25519/`.
Custom firmware flashed; KAT prints `M2 PASS: Ed25519 KAT matches TSL vector`.

### M3. Signed poll against the real DMZ

Implement `src/config.toit` (constants from section 1) and `src/protocol.toit`
(build body per section 3, parse `response.command`, freshness compare). Wire
NTP first: use the `ntp` package, sync the clock, and refuse to POST until the
clock is believable (e.g. year >= 2024).

```bash
jag pkg install ntp
jag pkg install http
```

Loop: NTP sync -> build body (fallback sensor values 1.0/1.0 for now) -> sign
(M2) -> POST with 600 s timeout -> parse -> log outcome -> repeat. Backoff 5 s on
network error.

Check M3: on `jag monitor` you see a successful `POST` (HTTP 200) and a parsed
response. Confirm on the DMZ side that the office zone shows a recent sensor
report from backend `esp32s3`. Cold-start body must omit `command`.

### M4. IR transmit (Midea / Coolix)

Implement `src/ir.toit` per section 5 (port the frame bytes from
`pico2w/src/ir.rs`; new RMT transmit layer). Wire it into the loop: when
`response.command.created_dt` is strictly newer, build frames and transmit, then
set the in-memory last-applied command + created_dt so the next body echoes it.

Check M4: forcing a newer command from the DMZ causes exactly ONE IR send
(state packet x2 + D5 packet), and the NEXT POST body includes that command.
Verify the AC responds, or capture the waveform.

### M5. Real AHT20 sensor

Implement `src/sensor.toit`: I2C on SDA=8, SCL=9, addr 0x38. Read temp/humidity
and use them in the body. On read failure with sensor-not-required, fall back to
1.0 C / 1.0 % and keep polling (log the failure).

Check M5: real readings appear in the POST body; unplugging the sensor falls back
without crashing.

### M6. Status LED (optional)

Drive the onboard WS2812 (GPIO38 for v1.1, GPIO48 for v1.0) via `rmt`. Map the
Pico patterns: 1 pulse poll-start, 2 pulses before IR send, 3 pulses
startup/config, 4 pulses error. If skipped, keep `status_led_driver` reported as
`log_only`.

### M7. Local HTTP `/healthz` and `/logs` (optional)

Serve on port 5000 after WiFi+NTP. Match the Pico body shapes in
`pico2w/src/health.rs` and `OBSOLETE/src/protocol.rs` (`build_logs_body`):
`/healthz` returns the Pi/Pico health shape with esp32s3 details;
`/logs` returns up to 32 newest-first entries from a 64-entry in-memory ring.

### M8. Deploy integration + persistence

- Add a deploy path so the office zone deploys this runtime (see section 7).
- Package the app as a Jaguar container so it auto-starts on boot
  (`jag container install thermo-esp32s3 src/main.toit`), surviving power cycles without
  a laptop attached.

Check M8: power-cycle the board with no laptop; after WiFi+NTP it resumes signed
polling on its own.

--------------------------------------------------------------------------------

## 7. Build / deploy / dev loop wiring

Development (fast loop): `jag watch src/main.toit`.

Provisioning secrets (do NOT commit): read WiFi password from
`thermo/priv/esp32s3/office.env` and the Ed25519 seed derived from
`thermo/priv/zone/priv.pem` (section 4). Bake them into the device via a Jaguar
asset or a generated `secrets.toit` that is git-ignored, produced by a deploy
script analogous to `pico2w/install/deploy.sh`.

Persistent install (production): `jag container install thermo-esp32s3 src/main.toit`
so the app runs on boot. `jag firmware update` updates the VM over WiFi.

Jaguar naming (office zone): picopi onboard keeps `thermo-office`; this ESP32-S3
uses Jaguar device name `esp32s3-office` and container name `thermo-esp32s3`
(see `zone.env` `ESP32S3_JAGUAR_*`).

Zone integration: mirror the Pico pattern. `zones/office/zone.env` already sets
`ONBOARD_DEPLOY_BACKEND=esp32s3`. Add an `install/deploy.sh` in this directory
(new, Toit-flavored) that:
1. sources `zone.env` + `thermo/priv/esp32s3/office.env`,
2. derives the Ed25519 seed and writes the git-ignored `src/secrets.toit`,
3. runs `jag container install thermo-esp32s3 src/main.toit` (or `jag run` for testing).
Keep secrets out of tracked files; add `src/secrets.toit` to `.gitignore`.

--------------------------------------------------------------------------------

## 8. Proposed new file layout (Toit path)

```text
thermo/onboard/hardware/esp32s3/
  PLAN.md                 (this file)
  hat/                    (kept; physical HAT geometry)
  package.yaml            (jag pkg init)
  package.lock
  src/
    main.toit             wifi + ntp + poll loop + wiring
    config.toit           zone/DMZ/pin constants
    auth.toit             sha256 + ed25519 sign + headers
    protocol.toit         body builder, response parse, freshness
    ir.toit               midea frames + RMT transmit
    sensor.toit           AHT20 I2C read + fallback
    health.toit           optional /healthz + /logs (M7)
    led.toit              optional status LED (M6)
    secrets.toit          GIT-IGNORED, generated at deploy
  install/
    deploy.sh             new Toit deploy (M8)
  OBSOLETE/               untracked; old Rust/ESP-IDF attempt (reference only)
```

--------------------------------------------------------------------------------

## 9. Risks and how to handle them

- Ed25519 on Toit (highest): handled by the M2 gate and Appendix B fallback.
- 38 kHz IR timing: use RMT hardware carrier, never bit-bang from a task. If RMT
  carrier control is awkward in Toit's `rmt`, that is a second reason to fall
  back to MicroPython (Appendix B).
- Octal PSRAM (N16R8): Toit prebuilt handles it; MicroPython needs the SPIRAM
  build (Appendix B).
- GPIO8/9 (AHT20 I2C, remapped from the invalid GPIO35/36) - confirmed free on
  this N16R8 module; verify again if the HAT design changes.
- Clock/timestamp: never POST before NTP sync; the DMZ rejects bad timestamps.

--------------------------------------------------------------------------------

## 10. M0 bring-up learnings (2026-07-09)

Recorded after a real M0 session on this exact board (ESP32-S3 DevKitC-1
compatible, `S3-N16R8`, dual USB ports). Read this before repeating M0 on a
fresh board of the same kind; it will save hours.

### What worked well

- `brew install jaguar` (current Homebrew core formula) installed cleanly; the
  older `brew install toitlang/toit/jag` tap is deprecated. `jag setup`
  auto-downloaded the matching SDK (`v2.0.0-alpha.195` alongside `jag
  v1.68.0`); versions matched, no skew problems.
- `jag flash -c esp32s3 --partition-table esp32-ota-1c0000-16mb --baud 115200`
  flashed this 16 MB N16R8 board correctly in one shot via the CH343 UART
  bridge port. A separate `espflash`/raw `esptool` attempt on the same board
  (during the earlier Rust/ESP-IDF path) had failed to enter download mode;
  Jaguar's bundled esptool (Go, v5.1.0) worked reliably once the physical
  cabling was right.
- Once WiFi actually joined, `jag scan <ip>` (direct IP, not the bare
  interactive picker), `jag run <file>`, and the unmodified SDK example
  `examples/hello.toit` all worked exactly as documented on the first try:
  `Success: Sent 37KB code`, then `Hello, World!` on the console.
- `jag container list` / `jag ping` / `jag firmware` give real, jag-native
  introspection of the device (container names, version, liveness) without
  needing an ad hoc serial protocol.

### What was unclear or undocumented

- **Two USB ports, two roles, undocumented.** This board (a generic
  `S3-N16R8` DevKitC-1 clone) exposes native USB-JTAG/Serial (`jag monitor`'s
  default port) and a separate CH343 UART bridge (`jag flash`'s default
  port) as two different `/dev/cu.usbmodem*` devices. Nothing in `jag --help`
  or docs.toit.io says a board can have two ports with different roles, or
  which one carries console output (it turned out to be native USB only;
  CH343 stayed completely silent even during a full boot).
- **Native USB-JTAG "stuck in stub flasher" trap.** Any esptool-family
  operation that touches the native USB-JTAG interface (even a lightweight
  read like `chip-id`) can leave the chip parked in the ROM stub flasher.
  `esptool --after hard-reset` did NOT reliably return the chip to normal
  boot on this board; only a full physical power cycle (unplug both cables,
  wait, replug) recovered it. This cost most of the session's debugging
  time and looks like a known ESP32-S3 native-USB quirk that isn't called
  out anywhere in `jag flash --help` or the troubleshooting docs.
- **`jag scan` (no args) is not scriptable.** It always drops into an
  arrow-key TUI picker, even with exactly one device found. There is no
  documented flag to auto-select the sole/first result; passing the device's
  IP directly (`jag scan <ip>`) skips the picker, but this was found by
  trial, not from `--help` or the getting-started guide.
- **`jag monitor`'s raw wire format leaks through on decode failure.** The
  getting-started docs show clean `[wifi] DEBUG: connecting` / `INFO:
  program ... started` text, but the actual wire protocol is SLIP-framed
  (`0xC0` delimiters) with an `OHAI` handshake and binary system-message
  frames (heap stats, MAC address). When something in the decode path
  glitches (attach timing, or a chip still echoing esptool SYNC/READ_REG
  responses from the stub-flasher trap above), `jag monitor` prints the raw
  undecoded bytes instead of erroring or explicitly saying "not a running
  Toit console." There's no troubleshooting entry for "monitor prints
  binary garbage."
- **Octal-PSRAM pin reservation isn't called out near the examples that need
  it.** `examples/i2c.toit` (SDA=21, SCL=22) and `examples/gpio.toit`
  (pin 2) are only valid on a plain (non-S3, non-octal) ESP32 DevKit. Any
  ESP32-S3 module marked R8 or higher reserves GPIO33-37 for the internal
  octal SPI flash/PSRAM bus; copying those example pins onto an S3-N16R8
  board (as our own `zone.env` originally did with GPIO35/36) silently
  risks corrupting flash/PSRAM access instead of failing loudly.

### Feedback worth filing upstream (Jaguar / Toit maintainers)

1. Add a non-interactive flag to `jag scan` (e.g. `--first` or `--yes`) for
   the common single-device case, or at least document `jag scan <ip>` in
   `--help` as the intended scripting path, not only in tutorial prose.
2. Have `jag monitor` detect its own undecodable SLIP/system-message frames
   and print a clear diagnostic ("binary protocol frame; device may be in
   the ROM bootloader, try a power cycle" or "SDK/jag version mismatch")
   instead of dumping raw bytes.
3. Document that some ESP32-S3 boards expose two USB ports with different
   roles (native USB-JTAG-Serial vs. a discrete UART bridge chip), that
   `jag flash`'s and `jag monitor`'s default ports can legitimately differ,
   and how to tell which port carries console output before assuming
   silence means failure.
4. Call out, in `jag flash --help` or a troubleshooting page, that
   esptool-protocol interactions with the native USB-JTAG interface can
   leave the chip parked in the ROM stub loader in a way that only a
   physical power cycle (not a soft/RTS reset) recovers from. This is a
   known ESP32-S3 native-USB behavior and a one-line callout would have
   saved most of a debugging session.
5. Add a comment to `examples/i2c.toit` / `examples/gpio.toit` noting the
   pin choices are valid for the plain ESP32 DevKit only, and that ESP32-S3
   R8/R16 (octal PSRAM/flash) modules reserve GPIO26-37 -- newcomers copying
   these examples onto an S3-N16R8-class board will silently corrupt
   PSRAM/flash access rather than get an error.

--------------------------------------------------------------------------------

## 11. HOW to port picopi (not WASM -- rewrite in Toit)

This section answers: "Can we compile picopi (Rust) or Pi Zero (Python) to
something Jaguar runs?" **No.** Then: "So how do we actually port?"

### 11.1 What Jaguar runs (not WASM)

Jaguar is **not** a WASM runtime. It is a host tool that talks to a **Toit
virtual machine** already flashed on the ESP32. The deploy path is:

```text
host:  src/*.toit  --(Toit compiler)-->  snapshot (~30 KB bytecode + metadata)
host:  jag run / jag container install  --(WiFi HTTP)-->  device
device: Jaguar relocates snapshot into flash, VM interprets Toit bytecode
```

Facts to internalize:

| Myth | Reality |
| --- | --- |
| "Jag uses WASM" | **No.** Toit compiles to **proprietary Toit snapshots** (bytecode for the Toit VM). |
| "Compile Rust to WASM, jag loads it" | **No.** There is no `.wasm` loader on the device. |
| "Compile Python to WASM" | **No.** Same. |
| "Cross-compile picopi `.rs` to Toit" | **No.** No Rust-to-Toit toolchain exists. |
| "Run the Pi Zero Docker stack on ESP32" | **No.** Pi Zero is Linux + Python + Flask + Docker; ESP32 is bare metal. |

Toit *can* run on the desktop host (`toit hello.toit`), and someone once
compiled the **Toit VM itself** to WASM for experiments -- but that is not a
supported Jaguar/ESP32 path and does not help us ship picopi unchanged.

Official references: Toit docs (containers/snapshots), Jaguar README (`jag run`
sends compiled programs over WiFi), Toit Take articles on the ESP32 VM and
snapshot format.

### 11.2 What "picopi" means in this repo

**picopi** = the onboard thermostat controller logic, today implemented as:

| Backend | Language | Location | Runs on |
| --- | --- | --- | --- |
| Pico2W (primary spec) | **Rust** | `thermo/onboard/hardware/pico2w/src/` | RP2350 bare metal |
| Pi Zero (legacy/host) | **Python** | `thermo/onboard/hardware/pizero2w/` + Docker | Linux on Pi |

Both speak the **same DMZ contract** (section 3). The ESP32-S3 port must
behave like picopi at the wire (HTTP headers, JSON body, IR timing, freshness
rules), not reuse picopi's object code.

The borgified container `thermo-esp32s3` on device `esp32s3-office` autostarts
M1 heartbeat only. M3+ must replace `src/main.toit` before the device POSTs
to the DMZ.

### 11.3 What you CAN reuse from picopi (copy, do not compile)

Treat Pico2W Rust as the **spec + test oracle**:

1. **Protocol constants** -- section 3 of this PLAN (already extracted).
2. **Per-module behavior** -- table in section 2; read the Rust file side by
   side while writing the matching `.toit` file.
3. **IR frame bytes** -- copy `midea_classic_frames` logic verbatim from
   `pico2w/src/ir.rs` (only the RMT transmit layer changes).
4. **Auth test vectors** -- `pico2w/src/auth.rs` unit tests; cross-check Toit
   output with host `pynacl` (M2 gate).
5. **JSON field order and shapes** -- match `protocol.rs` / `health.rs` exactly.
6. **Pin map** -- section 1 (ESP32 GPIO numbers differ from Pico GP numbers).
7. **Deploy secrets pattern** -- same env files (`zone.env`, `priv/esp32s3/`,
   `priv/zone/priv.pem`); inject at deploy via Jaguar assets or git-ignored
   `src/secrets.toit` (section 7).

Do **not** expect `#include`, `extern crate`, or `import` from Rust/Python into
Toit. The "port" is **manual translation** module by module.

### 11.4 HOW to port picopi to Toit (step by step)

Follow milestones M2..M8 in order. For each Pico2W module:

```text
1. Read the Rust module (behavior + edge cases + unit tests).
2. Create the matching src/<name>.toit listed in section 2.
3. Use Toit stdlib/packages instead of Rust crates:
     Rust std / embassy     ->  Toit tasks, gpio, i2c, rmt, net, http
     Rust ed25519-dalek      ->  M2: package search OR Appendix B fallback
     Rust heapless::String   ->  Toit strings (mind allocation on ESP32)
4. Keep function names and data flow parallel to Rust where it helps diff review.
5. jag run src/<module-test>.toit  OR  jag watch src/main.toit  on esp32s3-office.
6. Pass the milestone check in section 6 before the next module.
7. When main loop works: jag container install thermo-esp32s3 src/main.toit
   (install/deploy.sh does rename + borgify).
8. Verify DMZ: manage zones office  and  manage logs  show backend esp32s3.
```

Suggested implementation order (dependencies):

```text
M2 auth.toit          (gate -- may force Appendix B)
M3 config.toit + protocol.toit + main.toit poll skeleton (unsigned POST first,
    then add signing once M2 passes)
M4 ir.toit
M5 sensor.toit
M6 led.toit (optional)
M7 health.toit (optional)
M8 container autostart + install/deploy.sh secrets generation
```

WiFi on ESP32 is **already configured at `jag flash` time** (Jaguar service
joins `lumiere`). Application code uses `net` / `http` packages; it does not
re-implement WiFi join like Pico's `embassy-net` path unless you run with
`-D jag.wifi=false` (see Toit wifi example).

### 11.5 Could we use WASM anyway?

**Not on this path.** Summary:

| Source | Compile to WASM? | Run on Jaguar ESP32? |
| --- | --- | --- |
| picopi Rust | rustc `--target wasm32` produces `.wasm` | **No** -- no WASM runtime on device |
| Pi Zero Python | Pyodide / similar | **No** -- same |
| Toit source | Toit -> snapshot (native path) | **Yes** -- this is the plan |
| Toit VM | Theoretically VM -> WASM (experiment) | **Not supported** for ESP32 bring-up |

WASM on microcontrollers (wasm3, WAMR, etc.) is a **different firmware stack**
entirely -- you would flash a WASM runtime instead of Jaguar/Toit, then port
picopi to WASM or use a WASM-target language. That abandons the Jaguar dev
loop (`jag watch`, containers, OTA) we already validated on this board.

### 11.6 Pi Zero Python -- why not "compile that"?

Pi Zero onboard is a **Linux server**:

- Flask app + twoway in Docker (`pizero2w/install/docker-compose.yml`)
- Full Python stdlib, `cryptography`, sockets, threads
- Ed25519 signing in Python is trivial

The ESP32 has **no Linux, no Docker, no CPython**. Options:

| Approach | Reuse Pi Python? | Fits Jaguar? |
| --- | --- | --- |
| Toit rewrite (this plan) | Logic only (read twoway/app for protocol) | Yes |
| MicroPython (Appendix B) | **Higher** -- port functions to `.py` | No Jaguar; use mpremote |
| Embed WASM/Python on ESP32 | Impractical at this scale | No |

If M2 (Ed25519 in Toit) fails, Appendix B is the closest "port Python thinking"
path: rewrite `auth.py`-style modules in MicroPython, not compile Pi Zero
sources.

### 11.7 MicroPython fallback (when Toit rewrite is blocked)

Appendix B remains the **whole-firmware** escape hatch if M2 or RMT IR fails.
It is also a manual port from picopi, but:

- Ed25519: pure Python or native `.mpy` (drop-in vs Toit's missing crypto)
- IR: `esp32.RMT` in MicroPython maps cleanly to section 5 timings
- Deploy: `mpremote` / `main.py` autostart, not `jag container install`

Do not mix Toit + MicroPython on one device.

### 11.8 Naming (Jaguar vs picopi vs DMZ)

| Name | Scope |
| --- | --- |
| `thermo-office` | Reserved for picopi onboard (user convention); do not reuse for ESP32 Jaguar device name |
| `esp32s3-office` | Jaguar **device** name (DHCP + `jag scan`) |
| `thermo-esp32s3` | Jaguar **container** name (borgified app autostart) |
| `backend: esp32s3` | DMZ JSON field -- what `manage logs` will show after M3 |

--------------------------------------------------------------------------------

## Appendix A. Quick command reference (Toit)

```bash
jag setup
jag flash                              # once, over serial
jag scan                               # find device on LAN
jag monitor                            # serial logs
jag run src/main.toit                  # run once over WiFi
jag watch src/main.toit                # live reload
jag pkg install ntp
jag pkg install http
jag container install thermo-esp32s3 src/main.toit   # persistent autostart
jag firmware update                    # update VM over WiFi
```

--------------------------------------------------------------------------------

## Appendix B. MicroPython fallback (use only if M2 fails)

Trigger: Ed25519 could not be made to work on Toit within budget (M2), or RMT IR
carrier proved unworkable. Then implement the ENTIRE firmware in MicroPython.
Everything in sections 1, 3, 4 (algorithm), and 5 (timings/frames) is identical.

Flashing (board is N16R8 = octal SPIRAM; pick the matching build):
```bash
pip install esptool mpremote
# get ESP32_GENERIC_S3 (SPIRAM / octal variant) .bin from micropython.org/download
esptool --chip esp32s3 --port <PORT> erase_flash
esptool --chip esp32s3 --port <PORT> --baud 460800 write_flash -z 0x0 ESP32_GENERIC_S3-*.bin
```

Dev loop with `mpremote`:
```bash
mpremote connect <PORT> repl          # REPL
mpremote run main.py                  # run a local script
mpremote cp main.py :                 # copy file to device
mpremote cp -r lib/ :                 # copy a directory
mpremote mount .                      # mount host dir for fast iteration
```

Ed25519 options (pick one):
1. Pure-Python: upload the `pure25519` module. Works on stock firmware, no
   recompile. Signing takes ~2-3 s, which is fine for a 600 s long-poll loop.
2. Native `.mpy`: a Monocypher-based `ed25519` natmod (~50 KB, ~12 ms/sign) can
   be uploaded to `:/lib/` on stock firmware, no firmware rebuild.
3. Custom firmware with `dmazzella/ucryptography` (mbedtls) built in as a
   USER_C_MODULE. Highest effort; only if 1 and 2 are unacceptable.

MicroPython module map:
```text
main.py            wifi (network.WLAN) + ntptime + poll loop
config.py          constants from section 1
auth.py            hashlib sha256 + ed25519 sign + headers (base64 standard)
protocol.py        body builder, response parse (ujson), freshness
ir.py              midea frames + RMT (esp32.RMT) 38 kHz carrier on GPIO17
sensor.py          AHT20 over machine.I2C (SDA=8, SCL=9, addr 0x38)
secrets.py         GIT-IGNORED wifi pw + ed25519 seed
```

MicroPython specifics:
- Time: `ntptime.settime()` before polling; refuse to POST until time is set.
- HTTP: `urequests` (long-poll: set socket timeout to 600 s) or raw `usocket`.
- IR: `esp32.RMT(pin=Pin(17), ...)` with carrier; send mark/space durations from
  section 5.
- I2C: `machine.SoftI2C` or `machine.I2C(sda=Pin(8), scl=Pin(9))`.
- Autostart: name the entry `main.py` so it runs on boot.

Same M3/M4/M5 checks as the Toit path apply.
