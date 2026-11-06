# Agent Notes -- esp32 / Volumio remote

Investigation plan and board notes: [`README.md`](README.md).

## KV boot (`todo:afc1dc50`)

The base bin loader is updated only over the marked USB wire. Actor images
and the start roster live in the writable KV image (`spinme/host/ta_kv.*`).
`ta_boot_from_kv` loads that roster and calls `init`; `exit` unregisters.
Do not add a second NVS or SPIFFS store for the same keys.
Python venv conventions for utils: root [`AGENTS.md`](../AGENTS.md).

## Python setup (volctrl)

Use a project-local `.venv` (not legacy `env/`):

```bash
cd esp32/volctrl
# from utils root:
../../create_pipenv.sh esp32/volctrl
. .venv/bin/activate
python -m volctrl discover
```

## Cursor / agent flash loop

Work with the ESP32 tree open: edit, then flash/monitor via PlatformIO (or
Arduino / ESP-IDF equivalent) in the integrated terminal:

```bash
pio run -t upload
pio device monitor
```

There is no separate Cursor CLI for the board loop. Prefer documenting the exact
flash command in-repo so the agent does not invent toolchain flags.
