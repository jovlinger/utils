# Board smoke checklist (todo:2370717b)

Date: 2026-11-01. Tooling: `spinme/.venv-tools/bin/pio`, port
`/dev/cu.usbmodem1101` (Espressif USB-JTAG).

## Off-device

- [x] `cd spinme/host && make test` green (incl. glass contract)

## On-device (Waveshare knob S3)

```bash
cd spinme/firmware/waveshare-knob-touch-lcd-1.8
../../.venv-tools/bin/pio run -e waveshare_knob_18_s3 -t upload \
  --upload-port /dev/cu.usbmodem1101
```

- [x] upload SUCCESS
- [x] serial: `display begin ok`
- [x] serial: `qspi exterior spike ok`
- [ ] serial `zlist ok/fail`: not observed within 15s (boot still in
  bench_probe after qspi spike); display path already proved
- [ ] Volumio clock/scroll/art/volume/transport: skipped -- `wifi.local.json`
  absent (empty SSID). Re-run with wifi + Volumio when credentials exist.
- [x] no panel-sized glass shadow in new host Draw path (per-shape local
  pixmaps + coverage list)

NONGOAL: emulator CI.
