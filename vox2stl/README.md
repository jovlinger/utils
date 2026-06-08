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

Geometry is parametric: the converter builds rectangular STL boxes for each
glyph rather than loading binary STL fragments. In full mode, `o` and `O` pads
are near-unit rectangular prisms with cylindrical through-holes subtracted.
Trace arm protrusions are clamped so they reach pad material without entering
the through-hole void.

Default `O` hole diameter is 125 percent of the `o` hole default. `o` and `O`
pad outer prisms use the same `unit - pad_gap` size so adjacent `OO` pads keep an
air gap.
