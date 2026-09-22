# Grader agent: score Toit implementation vs TSL

You grade a **fresh implementer's** ESP32-S3 Toit work against TSL. You are not
the implementer. Use this rubric; output PASS/FAIL per item and one paragraph summary.

## Inputs

- TSL tree: `thermo/onboard/spec/**/*.tspec.json`
- Implementation: `thermo/onboard/hardware/esp32s3/src/*.toit`
- Live checks: `jag ping`, `jag container list`, `manage zones office`, `manage logs`

## Rubric (all required for PASS)

### A. Spec fidelity

| ID | Check | PASS if |
| --- | --- | --- |
| A1 | Cold-start body | Exact match to `dmz/golden_cold_start.tspec.json` `expected_body_json` (no command field) |
| A2 | Auth SHA256 | Empty `{}` hash matches `auth/vectors.tspec.json` sha256_hex |
| A3 | Auth sign | Signature for pico unit-test vector matches host `cryptography` Ed25519 (88-char b64) |
| A4 | Freshness | Implements lexicographic strict `created_dt` per `controller.tspec.json` |
| A5 | NTP gate | No POST before clock believable (min year 2024) |
| A6 | IR timings | Uses TSL `ir/midea24_coolix.tspec.json` microseconds + carrier 38000 |
| A7 | IR frames | At least one golden `packets_hex` triple matches on-wire bytes |
| A8 | Profile pins | GPIO8/9 I2C, GPIO17 IR TX per `profiles/esp32s3_office.tspec.json` |

### B. Operational

| ID | Check | PASS if |
| --- | --- | --- |
| B1 | Container | `jag container list` shows `thermo-esp32s3` on `esp32s3-office` |
| B2 | DMZ visible | `manage zones office` shows recent sensor data with `backend` esp32s3 in deployment (or logs show successful POST) |
| B3 | Naming | Jaguar device is NOT `thermo-office` |

### C. Process

| ID | Check | PASS if |
| --- | --- | --- |
| C1 | No TSL drift | Implementer did not edit goldens to match bugs |
| C2 | Secrets | No WiFi password or Ed25519 seed in tracked files |

## Scoring

- **SHIP**: all A + B pass
- **PARTIAL**: A1-A5 pass but IR or DMZ live check missing
- **FAIL**: any of A1-A3 fail, or Ed25519 abandoned without documented Appendix B switch

Run host verification yourself; do not ask the user to paste logs.
