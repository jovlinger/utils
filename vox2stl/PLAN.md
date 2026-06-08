# vox2stl Geometry Plan

## Goal

Generate printable STL from `.vox` art by making features generous first, then
leaving explicit isolation gaps anywhere adjacent cells should not connect.

The `.vox` file is the electrical contract. The STL generator must not infer a
short just because two bulky pieces of geometry are adjacent.

## UNIT-Fraction Constants

All board geometry should be defined as fractions of `UNIT_MM`, then converted
to millimeters at runtime:

- `TRACE_WIDTH_FRAC`: trace body width.
- `PIN_HOLE_DIAMETER_FRAC`: Pico pin through-hole diameter.
- `LEG_HOLE_DIAMETER_FRAC`: module leg through-hole diameter.
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

- Holes: leg holes are 125 percent of pin holes.
- Pads: pin and leg pads are chunky, near one full unit, with through-hole
  cylinders subtracted.
- Traces: traces are chunky enough for slicers to create visible top-surface
  paths.
- Isolation: no-connect pairs get an explicit gap even if chunky features would
  otherwise touch.
- Labels: lowercase `.vox` letters render as uppercase block-letter shapes,
  one monospace letter per cell, and do not connect electrically.

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
