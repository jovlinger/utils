# volctrl — Volumio proof-of-concept controller

Discover a Volumio endpoint, read state, set volume, and control play/pause. Plain Python (stdlib for the API) so it can be ported to MicroPython.

## Quick start

From repo root, use the esp32 venv (see [esp32/README.md](../README.md) and [utils/README.md](../../README.md)):

```bash
cd esp32
python3 -m venv env && source env/bin/activate
pip install -r volctrl/requirements.txt   # optional: only for mDNS discover
python -m volctrl discover                 # find Volumio (volumio.local or zeroconf)
python -m volctrl state
python -m volctrl volume 50               # 0–100, or up / down
python -m volctrl play
python -m volctrl pause
python -m volctrl toggle
```

Host: set `VOLUMIO_HOST` or pass `--host 192.168.1.22`.

## Layout

- **api.py** — Volumio REST client (urllib + json only). Use this on MicroPython; replace `urllib` with `urequests` or raw socket if needed.
- **discover.py** — Optional: resolve `volumio.local` (no deps) or zeroconf mDNS (needs `zeroconf`).
- **__main__.py** — CLI entrypoint.

## Porting to MicroPython

- Keep **api.py** logic; swap `urllib.request` for `urequests.get()` or a small socket-based GET helper.
- Omit **discover.py** or implement a simple broadcast/scan; on device you can use a fixed IP or WiFi + hostname.
- Omit **__main__.py**; call `VolumioAPI(host).get_state()`, `.set_volume(...)`, `.toggle()` from your firmware.

## Requirements

- Python 3.9+
- Optional: `zeroconf` (for `discover()` mDNS browse). Core API and `volumio.local` resolve use stdlib only.
