# Waveshare Knob-Touch-LCD-1.8

Follow view on the S3. Core A is the Arduino loop (touch, encoder, dirty-row
push, backlight pin). Core B is pinned to core 0 and runs `uimk2_host` on the
event ring (`uimk2_event`, zlist `update_render_draw`, hit-test Toggle).

Player HTTP is not wired. The glass paints the design stand-in (zone, play,
Artist, Album, title, volume digits, desired overlay at alpha 128).

```bash
pio run -e waveshare_knob_18_s3
pio run -e waveshare_knob_18_s3 -t upload
```

`pio` is `spinme/.venv-tools/bin/pio` from the device-ui worktree when this
checkout has no venv. Do not upload any env other than `waveshare_knob_18_s3`.
