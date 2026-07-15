# Fresh agent: implement TSL on ESP32-S3 (Toit)

You are a **fresh implementer**. You have no prior chat context. The one true
runtime is **TSL JSON** under `thermo/onboard/spec/`. Do not invent behavior.

## Read first (in order)

1. `thermo/onboard/spec/README.md`
2. `thermo/onboard/spec/manifest.tspec.json`
3. Every document listed in the manifest (all `*.tspec.json` files)
4. `thermo/onboard/hardware/esp32s3/PLAN.md` sections 1, 3, 6 (M2-M8), 11
5. `thermo/onboard/spec/profiles/esp32s3_office.tspec.json`

## Target

| Setting | Value |
| --- | --- |
| Board | ESP32-S3 N16R8, already flashed with Jaguar |
| Device | `esp32s3-office` (or `jag scan 192.168.88.73`) |
| Container | `thermo-esp32s3` |
| Code dir | `thermo/onboard/hardware/esp32s3/src/` |

## Deliverables

Implement TSL `controller` + `dmz/request` + `auth/vectors` + `ir/midea24_coolix`
for the esp32s3_office profile. Suggested modules (match PLAN section 2):

- `config.toit` -- constants from profile + priv env (no secrets in git)
- `auth.toit` -- must pass `auth/vectors.tspec.json` (M2 gate)
- `protocol.toit` -- cold-start body must match `dmz/golden_cold_start.tspec.json` exactly
- `sensor.toit` -- AHT20 on GPIO8/9, fallback 21.0/50.0
- `ir.toit` -- RMT + golden frames from TSL
- `main.toit` -- poll loop per `controller.tspec.json`

## Deploy

```bash
cd thermo/onboard/hardware/esp32s3
jag scan esp32s3-office   # or jag scan <ip>
jag container install thermo-esp32s3 src/main.toit -d esp32s3-office
```

Or: `THERMO_ENV_FILE=onboard/zones/office/zone.env ./install/deploy.sh`

## Verification (you must run)

1. Host: derive expected signature for `auth/vectors.tspec.json` with Python
   `cryptography` and compare to your Toit signer output.
2. Build cold-start JSON in Toit; byte-compare to `expected_body_json` in golden file.
3. `jag run` / container install; `manage zones office` shows recent `backend: esp32s3`.
4. `manage logs` contains `esp32s3` or office sensor POST success (after NTP + WiFi).

## Hard rules

- JSON only in spec tree; do not add YAML.
- Do not change TSL to make failing code pass; fix code.
- Do not reuse Jaguar device name `thermo-office` (reserved for picopi).
- WiFi is already configured by Jaguar at flash; use Toit `net`/`http` packages.
- If Ed25519 cannot pass auth vectors in one session, stop and report (Appendix B).

## Out of scope for first pass

- `/healthz` and `/logs` local HTTP (optional in TSL)
- WS2812 LED patterns (status_led_driver log_only is fine)

Report: list files created, M2/M3 check results, and `manage zones office` snippet.
