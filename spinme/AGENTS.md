# Agent Notes -- esp32 / Volumio remote

Investigation plan and board notes: [`README.md`](README.md).

## KV boot (`todo:afc1dc50`)

The base bin loader is updated only over the marked USB wire. Actor images
and the start roster live in the writable KV image (`spinme/host/base/ta_kv.*`).
`ta_boot_from_kv` loads that roster and calls `init`; `exit` unregisters.
Do not add a second NVS or SPIFFS store for the same keys.

Python venv conventions for utils: root [`AGENTS.md`](../AGENTS.md).

## Design authority (TaskActor fabric)

Open tickets are SoT; keep the exposition under [`docs/`](docs/README.md)
aligned with them (stub: [`EXPOSITION.md`](EXPOSITION.md)). When told to
**update exposition**, edit the owning file listed in `docs/README.md`:

- `todo:afc1dc50` (done) -- KV layout/allocator, boot roster/load/`init`/`exit`, USB-only
  base bin loader, Net HTTP REST KV set / OTA payloads. Host path shipped; ELF map is still a stub.
- `todo:15b92eaa` -- Log actor, `ta_all_*`, Net NTP (consumes KV; does not own
  a second store). Host Log accept/drain and the init URL fetch are in
  `spinme/host/actor/ta_log_accept.*`.
- `todo:b946f61f` -- Lose monolithic Net; one TaskActor per protocol (Http, Ntp,
  QuLog/Rfc5424, Mpd, ...) each with its own select/state machine.

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

## Host layout

Library: `spinme/host/{event,shape,actor,base}/`. Tests under
`spinme/host/tests/`:

| Dir | Role |
|-----|------|
| `tests/local/` | PC unit + goldens (`make test`; e.g. `test_xy_timed_redraw`) |
| `tests/ondevice/` | Post-flash/OTA via `POST /event/Test/TestRun` |

Test actor accepts `TA_EV_TEST_RUN`; on PC forks `build/test_*`, on device
built-in probes (`smoke`). `tests/ondevice/` drives the board HTTP gateway.

## Cursor / agent flash loop

Prefer the spinme Makefile install targets (agent may only invoke `make` for
these; do not invent raw `pio` flags):

```bash
cd spinme
make usbinstallall       # build + full USB flash (nucleus + linked actors)
make usbinstalltasks     # stage task blobs; OTA PUT until USB tasks partition exists
make otainstalltasks     # stage + PUT /kv/<key> to SPINME_HOST (default spinme.local)
```

Env overrides: `UPLOAD_PORT`, `SPINME_HOST`, `SPINME_PIO`. Optional blobs live
under `ota_tasks/` (basename = KV key). `make clean` / `make distclean` wipe
host objects, staged tasks, and PlatformIO build (distclean also drops
`build/` and `firmware/.../.pio`).

Low-level equivalent (docs only):

```bash
pio run -t upload
pio device monitor
```

`pio` is `spinme/.venv-tools/bin/pio`. There is no separate Cursor CLI for the
board loop.
