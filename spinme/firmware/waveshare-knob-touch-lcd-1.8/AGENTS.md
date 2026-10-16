# Agent notes -- Waveshare knob flash

Flash this directory. An edit is on the glass only after upload exits 0.
The master checkout under `utils/spinme` is a scaffold. Build the
`branch:4a26154c-device-ui` worktree.

`pio` is not on `PATH`. The binary is the gitignored venv
`spinme/.venv-tools/bin/pio`. Do not install another PlatformIO and do
not invent toolchain flags. The upload port is `upload_port` in
`platformio.ini` (`/dev/cu.usbmodem1101`).

From this firmware directory, `make build` compiles and `make install`
flashes the UI. `make` expects `<spinme>/.venv-tools/bin/pio`. Equivalent
raw commands, with `<spinme>` the checkout that contains `.venv-tools`:

```bash
export PATH="<spinme>/.venv-tools/bin:$PATH"
pio run -e waveshare_knob_18_s3 -t upload
```

That env is also `default_envs`, so a bare `pio run -t upload` is the UI image. Do not upload `encoder_debug` when the glass should show the UI. Success prints `Hash of data verified` and `Hard resetting via RTS pin`.
Encoder-only image (no display), then watch the port while the knob is turned:

```bash
pio run -e encoder_debug -t upload
```

Build without flashing:

```bash
pio run
```

`pio device monitor` holds the same serial port. Stop it before the
next upload. If `.venv-tools/bin/pio` is missing, stop and ask. Do not
substitute a system `pio` or `python -m platformio`.
