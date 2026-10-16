# Agent Notes -- esp32 / Volumio remote

Investigation plan and board notes: [`README.md`](README.md).
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

Waveshare knob upload: [`firmware/waveshare-knob-touch-lcd-1.8/AGENTS.md`](firmware/waveshare-knob-touch-lcd-1.8/AGENTS.md).

`pio` is not on `PATH`. Use `spinme/.venv-tools/bin/pio`, then
`pio run -t upload` from that firmware directory. The glass does not
change until that upload exits 0.
