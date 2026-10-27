# Waveshare Knob-Touch-LCD-1.8

Follow view on the S3. Core A is the Arduino loop (touch, encoder, dirty-row
push, backlight pin). Core B is pinned to core 0 and runs `uimk2_host` on the
event ring (`uimk2_event`, zlist `update_render_draw`, hit-test Toggle).

Core B owns the player. On `player_poll` it GETs Volumio `getState`
(`miniDSP-SHD.local:3000` unless `-DVOLUMIO_HOST` / `-DVOLUMIO_PORT`) and
writes volume, play/pause/stop, and artist/album/title into the follow
glass. Toggle GETs `commands/?cmd=toggle` after the local playing flip.
A knob volume event GETs `commands/?cmd=volume&volume=N` once per burst.
HTTP runs off the Core A mutex.

WiFi comes from gitignored `include/wifi_local.h`, written by
`prepare_firmware.py` from the main checkout `spinme/wifi.local.json`
(`{"wifi": {"ssid": "...", "pass": "..."}}`). Do not commit that json or
header. Override with `-DWIFI_SSID` and `-DWIFI_PASS` (those replace the
header macros). An empty SSID still builds and logs `WIFI_SSID empty` plus
`player poll skipped: WIFI_SSID empty`.

Until the first poll lands, the glass still shows the boot stand-in. The
first poll copies the player volume onto desired so that stand-in does not
cover the real digits. Later polls leave desired alone.

```bash
pio run -e waveshare_knob_18_s3
pio run -e waveshare_knob_18_s3 -t upload
```

`pio` is `spinme/.venv-tools/bin/pio` from the device-ui worktree when this
checkout has no venv. Do not upload any env other than `waveshare_knob_18_s3`.

Boot prints one line for the host `short_title_noscroll` /
`update_render_draw` path (`esp_timer_get_time`, N=100). On 2026-10-27 that
mean was 17954.36 us against a Mac mean of 20.23 us (slowdown 887.51). See
`spinme/uimk2/BENCH.md`.
