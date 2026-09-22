# Fresh agent: implement TSL on ESP32-S3 (MicroPython)

You are a **fresh implementer**. You have no prior chat context. The one true
runtime is **TSL JSON** under `thermo/onboard/spec/`. Do not invent behavior.

Toit/Jaguar is retired for this board. Use MicroPython under
`thermo/onboard/hardware/esp32s3/mp/`. See `hardware/esp32s3/AGENTS.md` for
REPL / mpremote.

## Read first (in order)

1. `thermo/onboard/spec/README.md`
2. `thermo/onboard/spec/manifest.tspec.json`
3. Every document listed in the manifest (all `*.tspec.json` files)
4. `thermo/onboard/hardware/esp32s3/PLAN.md` sections 1, 3, Appendix B
5. `thermo/onboard/spec/profiles/esp32s3_office.tspec.json`
6. `thermo/onboard/hardware/esp32s3/AGENTS.md`

## Target

| Setting | Value |
| --- | --- |
| Board | ESP32-S3 N16R8, MicroPython SPIRAM build |
| Device | office LAN `192.168.88.73` (see zone.env) |
| Code dir | `thermo/onboard/hardware/esp32s3/mp/` |

## Deliverables

Implement TSL `controller` + `dmz/request` + `auth/vectors` + IR dialects for
the esp32s3_office profile. Suggested modules:

- `config.py` -- constants from profile + priv env (no secrets in git)
- `auth.py` -- must pass `auth/vectors.tspec.json`
- `protocol.py` -- cold-start body must match golden exactly
- `sensor.py` -- AHT20 on GPIO8/9, fallback 1.0/1.0
- `ir_midea.py` / `ir_daikin.py` -- keep in tree; upload only when ready
- `main.py` -- debug HTTP + later poll loop

## Deploy

```bash
cd thermo/onboard/hardware/esp32s3
THERMO_ENV_FILE=onboard/zones/office/zone.env ESP32S3_FLASH_PORT=/dev/cu.XXX \
  ./install/deploy.sh
```

Upload uses `install/upload.manifest` (IR dialects omitted by default).

## Verification

1. `make -C thermo/onboard/hardware/esp32s3 test`
2. `mpremote connect $PORT repl` / mount loop per AGENTS.md
3. After WiFi: `curl http://<ip>:5000/healthz` and `/logs`

## Hard rules

- JSON only in spec tree; do not add YAML.
- Do not change TSL to make failing code pass; fix code.
- Do not reintroduce Toit/Jaguar as the device runtime.
