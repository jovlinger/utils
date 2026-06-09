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
when present. In `--mode full`, the `base` layer becomes a plate and `*` / `O`
cells become through-holes.

## Trace Glyphs

- `-` creates a horizontal trace.
- `|` creates a vertical trace.
- Box-drawing corners, T junctions, and crosses connect only on their drawn arms.
- `+` is treated as a four-way cross.
- `*` and `O` create raised pad boxes.
- Lowercase `a` through `z` render embossed uppercase letters, one monospace
  letter per cell. They do not connect electrically. Letter shapes come from
  pre-rendered smoothed Hershey vector tiles in `vox2stl/tiles/letters/`.

## Geometry Constants

Default dimensions are expressed as fractions of `UNIT_MM` in `constants.py`:

- `TRACE_WIDTH_FRAC = 0.72 * (0.72 / 0.88)`
- `ADJACENT_ISOLATION_GAP_FRAC = 0.12`
- `PIN_HOLE_DIAMETER_FRAC = (1.10 * 0.66) / 2.54`
- `LEG_HOLE_DIAMETER_FRAC = 1.10 / 2.54`
- `PIN_OUTSIDE_FRAC = 0.72`
- `LEG_OUTSIDE_FRAC = 0.72`
- `TILE_OVERLAP_FRAC = 0.08`
- `TRACE_HOLE_CLEARANCE_FRAC = 0.04`
- `LABEL_RECESS_FRAC = 0.04`
- `LABEL_HEIGHT_FRAC = 0.40`

Geometry is parametric: the converter builds rectangular STL boxes for each
glyph rather than loading binary STL fragments. In full mode, `*` and `O` pads
are near-unit rectangular prisms with cylindrical through-holes subtracted.
Trace arms are emitted only when the neighboring cell connects by the `.vox`
rules, and protrusions are clamped so they reach pad material without entering
the through-hole void.

Default `O` hole diameter is the previous `*` hole default, while the current
`*` hole default is 66 percent of that size. `*` and `O` pad outer prisms use
the same outside fraction and are clamped by
`ADJACENT_ISOLATION_GAP_FRAC` so adjacent `OO` pads keep an air gap.

Label letters are inset from cell edges by `LABEL_RECESS_FRAC` to avoid
overhang. Their embossed height is `LABEL_HEIGHT_FRAC * UNIT_MM`, starting at
the trace layer base height.

Rebuild the persistent letter tile library after changing label geometry:

```bash
vox2stl/build_letter_tiles.py
```
