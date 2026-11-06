# Agent Notes -- esp32 / Volumio remote

Investigation plan and board notes: [`README.md`](README.md).
Python venv conventions for utils: root [`AGENTS.md`](../AGENTS.md).

## Design authority (TaskActor fabric)

Open tickets are SoT; keep [`EXPOSITION.md`](EXPOSITION.md) aligned with them:

- `todo:afc1dc50` -- KV layout/allocator, boot roster/load/`init`/`exit`, USB-only
  base bin loader, Net HTTP REST KV set / OTA payloads.
- `todo:15b92eaa` -- Log actor, `ta_all_*`, Net NTP (consumes KV; does not own
  a second store).

Base bin loader updates are **USB-wired only** (board-marked). Do not invent
OTA for that loader.

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
