# vox2stl Geometry Plan

## Goal

Generate printable STL from `.vox` art by making features generous first, then
leaving explicit isolation gaps anywhere adjacent cells should not connect.

The `.vox` file is the electrical contract. The STL generator must not infer a
short just because two bulky pieces of geometry are adjacent.

## Geometry Constants

Board geometry that scales with the `.vox` grid should be defined as fractions
of `UNIT_MM`, then converted to millimeters at runtime. Pin and leg holes are
physical diameters, so they stay absolute in millimeters:

- `TRACE_WIDTH_FRAC`: trace body width.
- `PIN_HOLE_DIAMETER_MM`: Pico pin through-hole diameter.
- `DEVICE_HOLE_DIAMETER_MM`: module leg through-hole diameter.
- `PIN_OUTSIDE_FRAC`: Pico pin pad outside width.
- `LEG_OUTSIDE_FRAC`: module leg pad outside width.
- `ADJACENT_ISOLATION_GAP_FRAC`: minimum air gap between adjacent cells that do
  not connect electrically.
- `TRACE_HOLE_CLEARANCE_FRAC`: minimum trace clearance from a through-hole void.
- `TILE_OVERLAP_FRAC`: small overlap across connected cell boundaries to help
  slicers fuse intended connections.
- `LABEL_RECESS_FRAC`: inset from cell edges for embossed letter glyphs.
- `LABEL_HEIGHT_FRAC`: embossed letter height above the trace-layer base.

Current intent:

- Holes: pin and leg holes use fixed physical diameters independent of
  `UNIT_MM`; only pin holes are enlarged from their previous value.
- Pads: pin and leg pads use the previous trace width as their exterior, with
  through-hole cylinders subtracted.
- Traces: traces are chunky enough for slicers to create visible top-surface
  paths.
- Isolation: no-connect pairs get an explicit gap even if chunky features would
  otherwise touch.
- Labels: lowercase `.vox` letters render as uppercase block-letter shapes,
  one monospace letter per cell, and do not connect electrically.

## Hardware Profiles

Split geometry constants into hardware facts and print-profile tuning. Hardware
profiles describe the board or carrier that the `.vox` layout targets; print
profiles describe the A1 mini slicer choices used to make the STL printable.

The first non-Pico profile should target the official Espressif
ESP32-S3-DevKitC-1 carrier with an ESP32-S3-WROOM-1 module. Espressif's
published header block lists two 22-pin headers, J1 and J3. The mechanical
drawing reports 2.54 mm pin pitch, 25.40 mm header row spacing, and about
63.50 mm by 27.94 mm board outline. Source:
`https://documentation.espressif.com/esp-dev-kits/en/latest/esp32s3/esp32-s3-devkitc-1/user_guide_v1.1.html`

Keep the layout-relevant differences small and explicit:

| Fact | Pico HAT profile | ESP32-S3-DevKitC-1 profile |
| --- | --- | --- |
| Header pitch | 2.54 mm | 2.54 mm |
| Header rows | 2 | 2 |
| Pins per header | 20 | 22 |
| Header row spacing | 17.78 mm | 25.40 mm |
| Grid intervals between headers | 7 | 10 |
| Board outline | Pico-derived HAT outline | 63.50 mm x 27.94 mm |
| Pin naming | `P1` through `P40` | J1/J3 header names from Espressif |

The `.vox` cell unit can stay 2.54 mm for both boards. The ESP32-S3 layout
skill should use the wider 10-interval header spacing and two extra rows per
side, while `vox2stl` should load the hardware profile so hole diameters,
header metadata, and default `UNIT_MM` come from the selected board instead of
Pico-specific constants.

Planned implementation:

1. Start a new hardware directory at
   `thermo/onboard/hardware/esp32s3_devkitc1/`.
2. Store a machine-readable ESP32-S3 hardware profile there, plus source notes
   for the Espressif dimensions and header table.
3. Add a matching Pico profile under `thermo/onboard/hardware/pico2w/`.
4. Add `--hardware-profile` to `vox2stl.py`; CLI overrides and `.vox`
   `UNIT_MM` metadata should still work.
5. Keep A1 mini slicer constants, such as trace width, isolation gap, overlap,
   and label dimensions, separate from hardware facts.

Shared HAT layout tooling belongs in `thermo/onboard/hardware/`: the ASCII
layout skill and `.vox` checker are reusable across board families. Generated
and hand-edited board artifacts stay in leaf directories such as
`thermo/onboard/hardware/pico2w/hat/` and the future
`thermo/onboard/hardware/esp32s3_devkitc1/hat/`.

## Chunky Then Subtract

For each trace-layer cell:

1. Start from a chunky center body for the glyph.
2. Add arm bodies only in the glyph's drawn connection directions.
3. Extend arms across a cell boundary only when the neighbor has the matching
   arm or pad connection.
4. If the neighbor pair should not connect, trim the local body at that boundary
   by `ADJACENT_ISOLATION_GAP_FRAC / 2`.
5. Clamp any arm approaching a through-hole so it reaches pad material but never
   enters the cylindrical hole void.
6. For `*` and `O`, create pad outside bodies and subtract the corresponding
   through-hole cylinder.
7. For lowercase `a` through `z`, create inset embossed uppercase letter strokes
   with no electrical arms.

## Connectivity Source Of Truth

The same arm rules should drive both:

- whether two neighboring glyphs connect; and
- whether the STL geometry is allowed to cross their shared boundary.

Examples:

- `-O` connects: horizontal trace may enter the pad's west side, but not the
  hole void.
- `OO` does not connect: adjacent pad outside bodies must keep an isolation gap.
- `||` side-by-side does not connect: parallel vertical traces keep an isolation
  gap between cells.

## Letter Tile Library

Lowercase `.vox` letters load pre-rendered uppercase tiles from
`vox2stl/tiles/letters/`. `build_letter_tiles.py` thickens Hershey Roman Simplex
stroke fonts, blurs the raster field for smooth edges, meshes the solid with
marching squares, simplifies to a triangle budget, and writes binary STL
fragments using the default label recess and height fractions. Runtime
placement scales and translates those triangles per cell.

## Future Tile Library

Trace and pad glyphs may eventually move to the same pre-rendered tile model.
Once dimensions settle, precompute STL fragments for each glyph and constant
set. The runtime placer should then load tile resources, translate them per
cell, and append triangles.
