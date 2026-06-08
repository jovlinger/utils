# vox2stl

Dependency-free `.vox` layer to ASCII STL converter.

## Usage

```bash
vox2stl/vox2stl.py path/to/file.vox --layer trace --output trace.stl
vox2stl/vox2stl.py path/to/file.vox --mode full --output board.stl
```

The input file must contain one or more layer headers:

```text
layer trace (offset, width, height)
```

Rows are sliced from `offset` for `width` characters. Cell coordinates are
centered around `(0, 0)` by default, with `UNIT_MM` read from a file comment
when present. In `--mode full`, the `base` layer becomes a plate and `o` / `O`
cells become through-holes.

## Trace Glyphs

- `-` creates a horizontal trace.
- `|` creates a vertical trace.
- Box-drawing corners, T junctions, and crosses connect only on their drawn arms.
- `+` is treated as a four-way cross.
- `o` and `O` create raised pad boxes.

## Geometry Constants

Default dimensions are expressed as fractions of `UNIT_MM` in `vox2stl.py`:

- `TRACE_WIDTH_FRAC = 0.72`
- `ADJACENT_ISOLATION_GAP_FRAC = 0.12`
- `PIN_HOLE_DIAMETER_FRAC = 1.10 / 2.54`
- `LEG_HOLE_DIAMETER_FRAC = PIN_HOLE_DIAMETER_FRAC * 1.25`
- `PIN_OUTSIDE_FRAC = 0.88`
- `LEG_OUTSIDE_FRAC = 0.88`
- `TILE_OVERLAP_FRAC = 0.08`
- `TRACE_HOLE_CLEARANCE_FRAC = 0.04`

Geometry is parametric: the converter builds rectangular STL boxes for each
glyph rather than loading binary STL fragments. In full mode, `o` and `O` pads
are near-unit rectangular prisms with cylindrical through-holes subtracted.
Trace arms are emitted only when the neighboring cell connects by the `.vox`
rules, and protrusions are clamped so they reach pad material without entering
the through-hole void.

Default `O` hole diameter is 125 percent of the `o` hole default. `o` and `O`
pad outer prisms use the same outside fraction and are clamped by
`ADJACENT_ISOLATION_GAP_FRAC` so adjacent `OO` pads keep an air gap.
