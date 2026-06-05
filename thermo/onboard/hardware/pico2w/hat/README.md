# Pico2W sensor HAT (3D-printed copper tape PCB)

First-iteration HAT STL for AHT20 + 38 kHz IR TX/RX modules on a Pico 2 W.

## Files

- `generate_sensor_hat_stl.py` -- parametric generator (no extra deps)
- `thermo-pico2w-sensor-hat-v1.stl` -- output mesh (mm, Z-up)

## Regenerate

```bash
python3 hat/generate_sensor_hat_stl.py
```

## Layout (v1)

- All 40 Pico header through-holes (1.1 mm) from the official KiCad footprint.
- Four Pico mounting holes (2.2 mm).
- Base plate 3.175 mm (1/8 in); raised trace pads 3.175 mm for copper tape.
- Center rails between header rows: 3V3 (west) and GND (east).
- Routed signals: GP4/SDA, GP5/SCL, GP14/IR TX, GP15/IR RX (see `PLAN.md`).
- Sensor pads (2.54 mm pitch): AHT20 row between rails; IR modules on left/right wings.
- USB pocket at the micro-USB end; avoid copper/material in the Pico 2 W antenna keepout (+Y end).

## Bambu A1 Mini (starting profile)

- Material: PLA or PETG structural layer; optional PA-CF for stiffness.
- Orientation: print with the flat base on the bed (Z = thickness axis).
- Layer height: 0.16--0.20 mm; perimeters 3+; infill 25--35 % gyroid.
- First layer: slow, clean brim around outer edge if corners lift.
- After print: press-fit Pico headers through holes, apply copper tape on raised traces, engravings are covered by tape.
