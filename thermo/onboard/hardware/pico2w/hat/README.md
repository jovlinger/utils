# Pico2W sensor HAT (3D-printed copper tape PCB)

Iteration HAT STL for AHT20 + 38 kHz IR TX/RX modules on a Pico 2 W.

## Files

- `generate_sensor_hat_stl.py` -- parametric generator (no extra deps)
- `../../SKILL.md` -- shared ASCII HAT layout rules
- `../../../../../vox2stl/voxtool.py` -- shared `.vox` validator and transformer
- `../../../../../vox2stl/vox2stl.py` -- top-level `.vox` trace-to-STL converter
- `PLAN.md` -- board orientation, coordinates, routes, and fabrication notes
- `thermo-pico2w-sensor-hat-v1-up-side.stl` -- solid base plate, trace-side component holes
- `thermo-pico2w-sensor-hat-v1-pico-side.stl` -- solid base plate, flat-side component holes
- `thermo-pico2w-sensor-hat-v1-up-side-vox.stl` -- full base, holes, and raised trace mesh from `up-side.vox`
- `thermo-pico2w-sensor-hat-v1-up-side-trace.stl` -- debug trace-only mesh from `up-side.vox`
- `thermo-pico2w-sensor-hat-v1.stl` -- legacy comparison mesh, not regenerated

## Regenerate

```bash
hat/generate_sensor_hat_stl.py
make -C thermo/onboard/hardware/pico2w hat-vox-stl
```

The `.vox` files and generated STL artifacts stay in this leaf `hat/` directory.
Reusable layout rules and validation live one hardware level up so future board
leaf dirs, such as ESP32-S3, can share them.

## Layout (v1)

- All 40 Pico header through-holes (1.1 mm) from the official KiCad footprint.
- Pico mounting holes are omitted to keep routing clear.
- Legacy base variants are solid plates only; the voxel STL includes base,
  holes, and raised traces from `up-side.vox`.
- Base plate 3.175 mm (1/8 in).
- Pico pin holes are 1.1 mm; sensor/module leg holes are 1.375 mm in voxel STL
  output (125 percent of Pico pin holes).
- Pico and sensor/module raised pad outer prisms use `PIN_OUTSIDE_FRAC` /
  `LEG_OUTSIDE_FRAC`, clamped by `ADJACENT_ISOLATION_GAP_FRAC`, with
  cylindrical through-holes subtracted.
- Sensor/module leg holes stay inside the Pico header rows.
- `pico-side` mirrors the trace-side pin map across X=0 for flat-side mounting.
- Top-side module pin order:
  AHT20 west-to-east: SDA, SCL, GND, 3V3.
  IR rows west-to-east: DAT/OUT, GND, 3V3.
- USB pocket at the micro-USB end; avoid copper/material in the Pico 2 W antenna keepout (+Y end).
- The board outline is tightened to about 2 mm outside the outer through-hole edges.

## Bambu A1 Mini (starting profile)

- Material: PLA or PETG structural layer; optional PA-CF for stiffness.
- Orientation: print with the flat base on the bed (Z = thickness axis).
- Layer height: 0.16--0.20 mm; perimeters 3+; infill 25--35 % gyroid.
- First layer: slow, clean brim around outer edge if corners lift.
- After print: choose `up-side` for modules on the raised trace side, or `pico-side` for modules on the flat side with pins passing through all layers.
- Generate voxel geometry with `hat-vox-stl` after `up-side.vox` passes
  `vox2stl/voxtool.py check`.
  Trace arms are emitted only across intended `.vox` connections and are
  clamped to reach pad material without entering the through-hole void.
