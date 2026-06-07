# Pico2W sensor HAT (3D-printed copper tape PCB)

Iteration HAT STL for AHT20 + 38 kHz IR TX/RX modules on a Pico 2 W.

## Files

- `generate_sensor_hat_stl.py` -- parametric generator (no extra deps)
- `PLAN.md` -- board orientation, coordinates, routes, and fabrication notes
- `thermo-pico2w-sensor-hat-v1-up-side.stl` -- solid base plate, trace-side component holes
- `thermo-pico2w-sensor-hat-v1-pico-side.stl` -- solid base plate, flat-side component holes
- `thermo-pico2w-sensor-hat-v1.stl` -- legacy comparison mesh, not regenerated

## Regenerate

```bash
python3 hat/generate_sensor_hat_stl.py
```

## Layout (v1)

- All 40 Pico header through-holes (1.1 mm) from the official KiCad footprint.
- Pico mounting holes are omitted to keep routing clear.
- Current variants are solid base plates only: no raised traces, pads, collars, labels, or dummy marks.
- Base plate 3.175 mm (1/8 in).
- Pico pin holes are 1.1 mm; sensor/module leg holes are 1.55 mm.
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
- Add traces only after the hole/base geometry slices and prints correctly.
