# Board smoke checklist (todo:2370717b, re-run todo:3135a46a)

Date: 2026-11-01 (TaskActor-only boot re-run 2026-11-02). Tooling:
`spinme/.venv-tools/bin/pio`, port `/dev/cu.usbmodem1101` (Espressif
USB-JTAG).

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
- [x] serial: `ta fabric_up=1`, `glass ok`, `draw task up` (TaskActor-only
  boot; no `uimk2_host` / Core-B ring, no `zlist` or `bench_probe` lines)
- [x] serial: `wifi ok`, `ta_net backend=player_http`, `player poll ...` at
  the 2 s Scheduler cadence (todo:3135a46a)
- [x] `query` shows clock/scroll/oneshot counters advancing; `rot N` /
  `tap X Y` reach Draw via ISR mail (`hits`, `isr`, `drops=0`)
- [x] albumart: `albumart calm ok ...` then base repaint
- [x] no panel-sized glass shadow in new host Draw path (per-shape local
  pixmaps + coverage list)

## END smoke (todo:3135a46a objid:000d) -- 2026-11-02

Volumio `http://192.168.88.163:3000/api/v1/getState` vs serial inject:

| Step | Serial | getState |
|------|--------|----------|
| baseline | (idle polls) | `pause` vol `51` |
| `rot 2` | `rot inject 2` then `player cmd ok (net)` | vol `53` (still pause) |
| `tap 180 26` | `tap inject` then `player cmd ok (net)` | `play` vol `53` |
| `query` | `desired=53 polled=53 hits=5 isr=5 drops=0 toggles=3` | matches |

Host `make test` green at the same tip. NONGOAL: Sonos. NONGOAL: emulator CI.
