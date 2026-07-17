# Pico2W HAT bookmark

In-progress state. Static fabrication notes: [`README.md`](README.md). Layout rules:
[`../../SKILL.md`](../../SKILL.md).

Last updated: 2026-07-07.

## Where we are

- `up-side.vox` and `pico-side.vox` have a **trace layer** with AHT20 and IR targets
  (GP28/GP27 I2C, GP10 IR TX, GP13 IR RX per firmware defaults).
- `voxtool.py check up-side.vox` **fails**: layer `base` has 26 rows but the header
  declares height 22 -- fix layer dimensions or row count before treating the file as valid.
- Open routing FIXME at bottom of `up-side.vox`: how to tie the `3V3` rail cleanly
  (`# FIXME: how best to make VCC == 3V3?`).

## Immediate next steps

1. Reconcile layer header row count with actual diagram rows in `up-side.vox`.
2. Resolve the `3V3` / VCC rail junction without shorting unrelated nets.
3. Re-run `vox2stl/voxtool.py check` on both `up-side.vox` and `pico-side.vox`.
4. Regenerate STL when check passes: `make -C thermo/onboard/hardware/pico2w hat-vox-stl`.

Former `PLAN.md` slicer essay and stale "trace mismatch" notes were removed; overlap
and non-manifold guidance lives in [`../../SKILL.md`](../../SKILL.md).
