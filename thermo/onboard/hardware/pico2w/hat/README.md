# Pico2W sensor HAT (3D-printed copper tape PCB)

First-iteration HAT STL for AHT20 + 38 kHz IR TX/RX modules on a Pico 2 W.

## Files

- `generate_sensor_hat_stl.py` -- parametric generator (no extra deps)
- `PLAN.md` -- board orientation, coordinates, routes, and fabrication notes
- `thermo-pico2w-sensor-hat-v1-up-side.stl` -- trace-side component variant
- `thermo-pico2w-sensor-hat-v1-pico-side.stl` -- flat-side component variant
- `thermo-pico2w-sensor-hat-v1.stl` -- legacy alias of the `up-side` variant

## Regenerate

```bash
python3 hat/generate_sensor_hat_stl.py
```

## Layout (v1)

- All 40 Pico header through-holes (1.1 mm) from the official KiCad footprint.
- Four Pico mounting holes (2.4 mm).
- Top surface has three functional heights: base, mid-height unconnected collars, and highest traces.
- Base plate 3.175 mm (1/8 in); unconnected collars rise 1.25 mm; traces rise 3.175 mm above the base.
- Trace width is 1.35 mm; center rails are 1.775 mm.
- Pico pads are 1.7 mm square; sensor/module pads are 2.35 mm square with 2.1 mm through-holes.
- Center rails between header rows: GND (west) and 3V3 (east).
- Routed signals: GP4/SDA, GP5/SCL, GP14/IR TX, GP15/IR RX (see `PLAN.md`).
- Sensor pads and traces stay inside the Pico header rows.
- Top-side module pin order is routing-friendly for one copper layer:
  AHT20 west-to-east: SDA, SCL, GND, 3V3.
  IR rows west-to-east: DAT/OUT, GND, 3V3.
- USB pocket at the micro-USB end; avoid copper/material in the Pico 2 W antenna keepout (+Y end).
- The board outline is tightened to about 2 mm outside the outer through-hole edges.
- `USB`, stacked `UP`/`SIDE`, and stacked `PICO`/`SIDE` are embossed as mid-height orientation marks.

## Bambu A1 Mini (starting profile)

- Material: PLA or PETG structural layer; optional PA-CF for stiffness.
- Orientation: print with the flat base on the bed (Z = thickness axis).
- Layer height: 0.16--0.20 mm; perimeters 3+; infill 25--35 % gyroid.
- First layer: slow, clean brim around outer edge if corners lift.
- After print: choose `up-side` for modules on the raised trace side, or `pico-side` for modules on the flat side with pins passing through all layers.
- Apply copper tape only on the highest trace/pad features; mid-height collars are intentionally unconnected.
