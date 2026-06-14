# ESP32-S3 Thermostat Controller Plan

## Board Target

Target the ESP32-S3 dev-kit family marked `S3-N16R8` on the module and sold as
an ESP32-S3 dev kit. `N16R8` identifies the flash/PSRAM module variant more than
the carrier geometry, so the layout should follow the DevKitC-compatible header
grid and keep the board outline as a profile field.

Primary source geometry:

- Espressif ESP32-S3-DevKitC-1 v1.1 header docs:
  `https://docs.espressif.com/projects/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html`
- Espressif mechanical DXF:
  `https://dl.espressif.com/dl/schematics/esp_idf/DXF_ESP32-S3-DevKitC-1_V1.1_20220429.dxf`
- Waveshare N16R8-family docs say their carrier is pin-compatible with
  ESP32-S3-DevKitC-1:
  `https://www.waveshare.com/wiki/ESP32-S3-DEV-KIT-N8R8`

## Measurement Check

The Pico2W pins used as a ruler validate the chosen header family:

- In-row pin spacing matches the Pico pitch, so use `2.54 mm`.
- Each ESP32-S3 row has two more pins than the Pico rows, so use `22` pins per
  side instead of `20`.
- The measured row-to-row distance is close to a DevKitC-style wide carrier.
  Use the precise Espressif center-to-center value, `25.40 mm`, for generated
  geometry. That is `10` pitch intervals center-to-center; an inner-edge visual
  estimate reads closer to `9` pitch intervals.

## Layout Facts

| Fact | Value |
| --- | --- |
| Hardware directory | `thermo/onboard/hardware/esp32s3/` |
| Unit pitch | `2.54 mm` |
| Header rows | `2` |
| Pins per row | `22` |
| Header center spacing | `25.40 mm` |
| Header center spacing in grid intervals | `10` |
| Initial `.vox` width | `13` columns including border columns |
| Initial `.vox` height | `24` rows including north/south border rows |
| Official Espressif outline | about `62.74 mm x 27.94 mm` |
| Waveshare N16R8-family outline | about `63.3 mm x 25.4 mm` |

The current `up-side.vox` captures the DevKitC-compatible header grid plus the
first routed sensor and IR module placement. It is the source of truth for the
pin assignment below.

## Pin Rows

Rows are north to south, pairing J1 and J3 pin numbers from the Espressif
DevKitC-1 header tables:

| Row | J1 | J3 |
| --- | --- | --- |
| 1 | `3V3` | `GND` |
| 2 | `3V3` | `GPIO43` / `TX` |
| 3 | `RST` | `GPIO44` / `RX` |
| 4 | `GPIO4` | `GPIO1` |
| 5 | `GPIO5` | `GPIO2` |
| 6 | `GPIO6` | `GPIO42` |
| 7 | `GPIO7` | `GPIO41` |
| 8 | `GPIO15` | `GPIO40` |
| 9 | `GPIO16` | `GPIO39` |
| 10 | `GPIO17` | `GPIO38` |
| 11 | `GPIO18` | `GPIO37` |
| 12 | `GPIO8` | `GPIO36` |
| 13 | `GPIO3` | `GPIO35` |
| 14 | `GPIO46` | `GPIO0` |
| 15 | `GPIO9` | `GPIO45` |
| 16 | `GPIO10` | `GPIO48` |
| 17 | `GPIO11` | `GPIO47` |
| 18 | `GPIO12` | `GPIO21` |
| 19 | `GPIO13` | `GPIO20` |
| 20 | `GPIO14` | `GPIO19` |
| 21 | `5V` | `GND` |
| 22 | `GND` | `GND` |

## Pin Assignment From `hat/up-side.vox`

Read from the trace-layer row comments in
`thermo/onboard/hardware/esp32s3/hat/up-side.vox`:

| Function | Module leg order in vox | ESP32-S3 net | Direction | Notes |
| --- | --- | --- | --- | --- |
| IR receiver signal | row `GPIO6`, `.c4` | `GPIO6` | Input | 38 kHz demodulated IR receiver `OUT`/`DAT`. |
| IR receiver power | row `GPIO6`, `.c5` | `3V3` | Power | Power the IR receiver from 3.3 V unless the module is requalified. |
| IR receiver ground | row `GPIO6`, `.c6` | `GND` | Ground | Shared board ground. |
| IR transmitter signal | row `GPIO17`, `.c4` | `GPIO17` | Output | 38 kHz carrier output for the IR transmitter module. |
| IR transmitter power | row `GPIO17`, `.c5` | `3V3` | Power | Power the IR transmitter from 3.3 V unless a later driver stage is added. |
| IR transmitter ground | row `GPIO17`, `.c6` | `GND` | Ground | Shared board ground. |
| AHT20 VCC | row `GPIO3/GPIO35`, `.c5` | `3V3` | Power | AHT20 supply. |
| AHT20 GND | row `GPIO3/GPIO35`, `.c6` | `GND` | Ground | Shared board ground. |
| AHT20 SCL | row `GPIO3/GPIO35`, `.c7` | `GPIO36` | Output/open-drain | ESP32-S3 I2C clock with pull-up to 3.3 V. |
| AHT20 SDA | row `GPIO3/GPIO35`, `.c8` | `GPIO35` | Bidirectional/open-drain | ESP32-S3 I2C data with pull-up to 3.3 V. |

Avoid ESP32-S3 boot strapping pins for first-port signals. The current placement
does not use `GPIO0`, `GPIO45`, or `GPIO46`. Before production, confirm the exact
N16R8 carrier does not reserve `GPIO35` or `GPIO36` for board-local flash, PSRAM,
USB, or other carrier functions; the DevKitC header exposes them for this design.

## Major Design Decisions

### OS and Runtime

Use ESP-IDF with its FreeRTOS kernel and `esp-idf-svc`/`esp-idf-hal` Rust
bindings. This keeps the application in Rust like the Pico2W port while relying
on Espressif's production WiFi, TCP/IP, NVS, SNTP, watchdog, GPIO, I2C, RMT, and
HTTP server/client integrations.

The ESP32-S3 port is a `std` Rust firmware built against ESP-IDF, not a
bare-metal `no_std` firmware. The application logic must stay in host-testable
Rust modules with HAL-facing traits at the boundary.

### Core and Task Allocation

The ESP32-S3 has two Xtensa LX7 cores. Allocate them as follows:

| Core | Owner | Tasks |
| --- | --- | --- |
| Core 0, PRO CPU | ESP-IDF system side | WiFi driver, TCP/IP/lwIP, event loop, timers, SNTP, and other IDF-created high-priority tasks. |
| Core 1, APP CPU | Thermo application side | Main thermo app task, local HTTP server request handlers, AHT20 reads, IR transmit scheduling, IR receive capture when enabled, and status LED state machine. |

The `main` function initializes ESP-IDF services, starts networking, then creates
the thermo app task pinned to core 1. Do not run long blocking application work
on core 0. The app task may block in the outbound DMZ long-poll HTTP request
because the WiFi and TCP/IP system tasks remain schedulable on core 0.

### RTOS Requirements

The port requires these FreeRTOS features:

- Preemptive scheduling with both ESP32-S3 cores enabled.
- Task pinning, so the thermo app task can stay on core 1 and system network
  tasks can remain on core 0.
- Queues or channels for app-to-IR and app-to-log communication.
- Event groups or notifications for WiFi connected, IP acquired, SNTP synced,
  and shutdown/reconnect signals.
- Software timers or equivalent monotonic timers for retry backoff, watchdog
  feeding, LED blink cadence, and HTTP timeout enforcement.
- Task watchdog coverage for the main thermo app task and any long-lived
  hardware worker tasks.
- Microsecond timing from ESP-IDF RMT or a hardware timer for the 38 kHz IR
  waveform. Do not bit-bang carrier timing from a normal preemptible task.

## Application API Toward TCP/IP

### Outbound DMZ Client

The ESP32-S3 replaces the Pi Zero2W `app` plus `twoway` pair and the Pico2W
single-binary loop. It must send the same signed long-poll request:

```text
POST http://<dmz_host>:<dmz_port>/zone/<zone_name>/sensors
Content-Type: application/json
X-Zone-Signature: <base64url Ed25519 signature>
X-Zone-Timestamp: <unix epoch seconds>
X-Zone-Name: <zone_name>
```

The signing payload is:

```text
METHOD\nPATH\nTIMESTAMP_EPOCH_INT\nSHA256_HEX_OF_BODY
```

Default values:

| Field | Default |
| --- | --- |
| DMZ scheme | `http` |
| DMZ host | `jovlinger.duckdns.org` |
| DMZ port | `5000` |
| Path | `/zone/<zone_name>/sensors` |
| POST timeout | `600` seconds |
| Retry backoff | start at `5` seconds, cap at `60` seconds |

The request body shape is the Pico2W body shape with
`deployment.hardware_profile` set to `esp32s3_aht20_ir` and
`deployment.backend` set to `esp32s3`. On cold start the body omits `command`.
After an IR command is accepted and sent, the next body includes the last applied
command so DMZ can apply its strictly-newer gate.

The response is the existing DMZ `ZoneState` JSON. `command` may be `null`. A
command is new only when `response.command.created_dt` is lexicographically
greater than the last applied `created_dt` string. Missing `created_dt` is stale.

### Local HTTP Server

After WiFi, DHCP, and SNTP are ready, the firmware exposes an onboard HTTP server
on TCP port `5000`.

| Method and path | Purpose | Response contract |
| --- | --- | --- |
| `GET /healthz` | Machine-readable health summary. | JSON with `ok`, `service`, `hardware_backend`, `time`, `deployment`, `queues`, `log_storage`, and `esp32s3`. |
| `GET /logs` | Rolling in-memory firmware log. | JSON with up to 32 newest-first log entries from a 64-entry buffer. |

`GET /healthz` must keep the Pi Zero/Pico shape where practical. The ESP32-S3
details live under an `esp32s3` object:

```json
{
  "ok": true,
  "service": "onboard-app",
  "hardware_backend": "esp32s3",
  "time": "2026-06-14T21:00:00Z",
  "deployment": {
    "zone_name": "kitchen",
    "hardware_profile": "esp32s3_aht20_ir",
    "send_behavior": "ir_heatpump",
    "report_behavior": "sensor_readings",
    "sensor_driver": "aht20",
    "ir_transport": "esp32s3_rmt",
    "ir_device": "gpio17",
    "ir_protocol": "midea24_coolix"
  },
  "queues": {
    "daikin_size": 0,
    "daikin_capacity": 0
  },
  "log_storage": {
    "path": null,
    "type": "memory"
  },
  "esp32s3": {
    "uptime_seconds": 0,
    "wifi_ready": true,
    "sntp_ready": true,
    "last_poll_ok": false,
    "poll_successes": 0,
    "poll_errors": 0,
    "ir_sends": 0,
    "ir_stub_sends": 0,
    "free_heap_bytes": 0,
    "minimum_free_heap_bytes": 0,
    "app_core": 1
  }
}
```

No inbound command mutation API is part of this port. Commands still come from
the DMZ response to the signed sensor POST.

## Application API Toward Hardware

Keep hardware behind a narrow trait boundary so the same app core can run in
host tests with fake adapters.

```rust
pub trait ThermoHardware {
    fn read_aht20(&mut self) -> Result<SensorReading, HardwareError>;
    fn send_midea_ir(&mut self, command: &HeatpumpCommand) -> Result<(), HardwareError>;
    fn send_raw_ir(&mut self, carrier_hz: u32, durations_us: &[i32]) -> Result<(), HardwareError>;
    fn record_ir_rx_edge(&mut self) -> Result<Option<IrEdge>, HardwareError>;
    fn set_status(&mut self, event: StatusEvent) -> Result<(), HardwareError>;
    fn monotonic_millis(&self) -> u64;
}
```

Required hardware adapter behavior:

| Adapter | Requirement |
| --- | --- |
| AHT20 I2C | Use `GPIO36` as SCL and `GPIO35` as SDA at 100 kHz or 400 kHz. Address defaults to `0x38`. Decode humidity and temperature using the existing AHT20 frame math. |
| Sensor fallback | If `SENSOR_BOOT_REQUIRED=0`, a read failure logs the error and reports 21.0 C and 50.0 %. If `SENSOR_BOOT_REQUIRED=1`, missing AHT20 is a boot failure. |
| IR transmit | Use ESP32-S3 RMT on `GPIO17` with 38 kHz carrier. Normal Midea/Coolix commands send two state frames and the Office secondary frame when required by the existing protocol rules. |
| Raw IR transmit | Accept DMZ `command_type=raw_ir_sequence` commands only when carrier is 38000 Hz and durations are nonzero, bounded, and no longer than 1024 entries. |
| IR receive | Use `GPIO6` for demodulated edge capture. First implementation may expose counters and raw capture plumbing without feeding closed-loop behavior. |
| Status LED | Prefer the DevKitC onboard addressable LED if available on the target carrier. If absent, status events must still be logged and `GET /healthz` must report `status_led_driver="log_only"`. |
| Storage | Store WiFi credentials and the Ed25519 zone private key in ESP-IDF NVS or compile them from the deployment environment for first bring-up. Do not persist command state across firmware erase unless explicitly configured. |

## Architecture Sketch for Vendor Tests

### Layers

The firmware is organized into these layers:

| Layer | Responsibility | Test handle |
| --- | --- | --- |
| `protocol` | Build sensor POST JSON, parse DMZ `ZoneState`, compare command freshness, encode health JSON. | Host unit tests with fixed JSON strings. |
| `auth` | Build signing payload and Ed25519 headers. | Host unit tests with fixed key/body/path/timestamp vectors. |
| `ir` | Parse heatpump command JSON, encode Midea/Coolix frames, expand raw IR durations. | Host unit tests over byte frames and duration lists. |
| `app_core` | One poll iteration: read sensors, build signed POST, classify response, call IR only for new commands, update state and logs. | Host integration tests with fake network and fake hardware. |
| `net_esp32s3` | WiFi, SNTP, outbound HTTP client, local HTTP server. | Hardware-in-loop or IDF component tests with a fake DMZ server. |
| `hw_esp32s3` | I2C AHT20, RMT IR TX, GPIO/RMT IR RX, status LED, NVS. | Hardware-in-loop tests or adapter tests with fakes. |
| `main` | ESP-IDF initialization, task creation, core pinning, watchdog registration. | Boot log and health endpoint assertions. |

### Main Runtime Flow

```text
BOOT
  initialize logging and rolling log
  read compile-time config and NVS secrets
  initialize WiFi station
  wait for connected and IP acquired
  run SNTP until timestamp is valid for DMZ signing
  start local HTTP server on port 5000
  create thermo app task pinned to core 1

THERMO APP TASK
  last_applied_created_dt = ""
  loop forever:
    log "poll start"
    read AHT20 or fallback according to SENSOR_BOOT_REQUIRED
    build POST body with sensors and optional last command
    sign body with Ed25519
    POST to DMZ long-poll endpoint
    on network/HTTP/sign/parse failure:
      log error, increment poll_errors, set error status, back off
    on 200 response:
      parse ZoneState
      if command.created_dt is strictly newer:
        transmit command over IR
        record command as last applied only after IR transmit succeeds
      increment poll_successes and continue immediately
```

### Black-Box Acceptance Tests

An outside vendor can write meaningful tests from these contracts without source
access:

- With fake AHT20 returning 23.7 C and 51.2 %, the first DMZ POST contains those
  values, omits `command`, reports `hardware_profile="esp32s3_aht20_ir"`, and
  includes valid Ed25519 headers for the body and path.
- With the DMZ responding `{"command":null}`, no IR transmit occurs and the next
  poll does not include a command.
- With a DMZ command whose `created_dt` is newer, exactly one IR send is attempted
  before that command appears in the next POST body.
- With the same or older `created_dt`, no additional IR send occurs.
- If AHT20 read fails and `SENSOR_BOOT_REQUIRED=0`, the POST reports 21.0 C and
  50.0 %, logs the sensor failure, and keeps polling.
- If AHT20 read fails and `SENSOR_BOOT_REQUIRED=1`, boot fails before entering
  the poll loop and `/healthz` either is unavailable or reports `ok=false`.
- If SNTP has not produced a valid time, the firmware does not send signed DMZ
  POSTs.
- `GET /healthz` on port 5000 returns `hardware_backend="esp32s3"`, the ESP32-S3
  deployment metadata, WiFi/SNTP readiness, poll counters, heap fields, and
  `app_core=1`.
- `GET /logs` returns newest-first log entries and never more than 32 entries.
- IR output on `GPIO17` uses a 38 kHz carrier and the Midea/Coolix timing
  constants from the Pico2W implementation: 4500 us header mark, 4500 us header
  space, 560 us bit mark, 560 us zero space, 1680 us one space, and about
  5200 us packet gap.
- IR receive input on `GPIO6` can count or timestamp demodulated edges without
  disrupting the poll loop.

## Next Steps

1. Keep `UNIT_MM=2.54` in `.vox` files.
2. Add trace intents to the ESP32-S3 vox once the current trace routing is
   confirmed against the physical DevKitC-compatible board.
3. Implement the port as host-testable Rust modules first, then attach ESP-IDF
   adapters for WiFi/HTTP, NVS, I2C, RMT, GPIO, and local HTTP serving.
