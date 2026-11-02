# Waveshare Knob-Touch-LCD-1.8

TaskActor-only boot on the S3. There is no second UI stack: the old Core-B
`uimk2_host` event ring / zlist path is retired (sources parked, unbuilt, under
`retired/uimk2_paint/`; see its README).

`setup()` runs `ta_device_boot()` (Init registers Logger, Draw, Net,
Scheduler, Controller/Router, MPDController, Sonos; posts `SET_ROUTE
MPDController` + `SET_ACTIVE`; arms the Draw clock/scroll cadences; spawns a
small `ta_fabric` task that only drains the Logger), binds the glass glue
(`ta_glass_device`: glyph atlas, base art, `panel_push_pack66`), then starts
the FreeRTOS task `ta_draw` pinned to core 0. That task is the sole glass
owner and the only fabric runner: it pumps Draw's queue, ticks the Scheduler
(1 Hz clock, scroll, album-change oneshots), and pumps the non-blocking
`player_http` socket that backs the Net actor.

Input never touches the glass directly. The encoder ISR and the CST816 touch
sampler post into two single-producer ISR mails; Draw drains them, hit-tests,
and posts ControlEvents to the Router -> MPDController -> Net (`player_http`)
-> `POLL_DONE` / `SET_DONE` back to Draw. The Arduino `loop()` only samples
touch over I2C and services the serial line.

Volumio is `miniDSP-SHD.local:3000` unless `-DVOLUMIO_HOST` /
`-DVOLUMIO_PORT`. Poll cadence is the Scheduler's fixed 2 s. Album art is
decoded (TJpgDec NN), calmed (`ta_artwork`), and installed as the base Shape.

WiFi comes from gitignored `include/wifi_local.h`, written by
`prepare_firmware.py` from the main checkout `spinme/wifi.local.json`
(`{"wifi": {"ssid": "...", "pass": "..."}}`). Do not commit that json or
header. Override with `-DWIFI_SSID` and `-DWIFI_PASS` (those replace the
header macros). An empty SSID still builds and logs `WIFI_SSID empty` plus
`player poll skipped: WIFI_SSID empty`.

```bash
pio run -e waveshare_knob_18_s3
pio run -e waveshare_knob_18_s3 -t upload
```

`pio` is `spinme/.venv-tools/bin/pio`. Do not upload any env other than
`waveshare_knob_18_s3`. Shared host sources are symlinked under
`src/ta_host/` (recreate per its README after a clone).

Serial smoke (115200): `spinme fabric: ...`, `display begin ok`,
`ta fabric_up=1`, `glass ok`, `draw task up`, then `wifi ok` / `player poll`.
`query` dumps counters; `tap X Y` and `rot N` inject into the ISR mails.
Checklist: `spinme/host/SMOKE.md`.

`spinme/uimk2/` remains a standalone host library + bench (`uimk2/BENCH.md`)
and is not linked into this firmware.
