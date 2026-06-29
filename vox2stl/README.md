# vox2stl

Dependency-free `.vox` layer to ASCII STL converter.

## Usage

```bash
vox2stl/voxtool.py stl path/to/file.vox --output board.stl
```

Validate a board `.vox` file before generating geometry:

```bash
vox2stl/voxtool.py check thermo/onboard/hardware/pico2w/hat/pico-side.vox
vox2stl/voxtool.py check --all
vox2stl/voxtool.py correct thermo/onboard/hardware/pico2w/hat/up-side.vox
vox2stl/voxtool.py mirror thermo/onboard/hardware/pico2w/hat/up-side.vox -out thermo/onboard/hardware/pico2w/hat/pico-side.vox
```

The input file must contain one or more layer headers:

```text
layer trace (offset, width, height)
```

Rows are sliced from `offset` for `width` characters. Cell coordinates are
centered around `(0, 0)` by default, with `UNIT_MM` read from a file comment
when present. During STL generation, the `base` layer becomes a plate and
`*` / `O` cells become through-holes.

## Trace Glyphs

- `-` creates a horizontal trace.
- `|` creates a vertical trace.
- Box-drawing corners, T junctions, and crosses connect only on their drawn arms.
- `+` is treated as a four-way cross.
- `*` and `O` create raised pad boxes. Pads accept traces from any side, but
  adjacent pad cells such as `OO` do not connect directly to each other.
- Lowercase `a` through `z` render embossed uppercase letters, one monospace
  letter per cell. They do not connect electrically. Letter shapes come from
  pre-rendered smoothed Hershey vector tiles in `vox2stl/tiles/letters/`.

For hand editing, `voxtool.py correct` rewrites ASCII trace shorthand in place:

- `/` and `\` are inferred as corners from neighboring trace arms, so a square
  can be written as `/\` over `\/`.
- `<` becomes `BOX_T_LEFT` (arms N/W/S); `>` becomes `BOX_T_RIGHT` (arms N/E/S).
- `^` becomes the upside-down T junction.
- Spaces inside the layer design window become `.`.

The direct shorthand characters `<`, `>`, and `^` are also treated as their
box-drawing equivalents during validation and STL generation.

Alias declarations let one-character glyphs carry net intent while still
rendering and connecting as an existing trace glyph:

```text
alias V -> | = VCC
alias G -> | = GND
```

Aliases are left in place by `correct`. During validation and STL generation,
the alias glyph behaves like the target glyph. During validation, each alias cell
also asserts the declared net, so disconnected power markers report net errors
instead of invalid-character or non-copper errors. Inline `.cN=NET` notes declare
expected net membership too, and cells with the same net name must be connected.

`voxtool.py mirror` mirrors each layer left to right, swaps row labels between
the left and right sides, and mirrors `.cN` notes and trace intent endpoints.

## Geometry Constants

Most default dimensions are expressed as fractions of `UNIT_MM` in `constants.py`.
Pin and device-leg hole diameters are absolute millimeter values:

- `TRACE_WIDTH_FRAC = 0.72 * (0.72 / 0.88)`
- `ADJACENT_ISOLATION_GAP_FRAC = 0.12`
- `PIN_HOLE_DIAMETER_MM = 1.10 * 0.66 * 1.50`
- `DEVICE_HOLE_DIAMETER_MM = 1.10`
- `PIN_OUTSIDE_FRAC = 0.88`
- `LEG_OUTSIDE_FRAC = 0.88`
- `TILE_OVERLAP_FRAC = 0.08`
- `COND_LIG_FRAC = 0.46`
- `ISOL_LIG_FRAC = 0.18`
- `GRID_FRAC = 0.04`
- `TRACE_HOLE_CLEARANCE_FRAC = 0.04`
- `LABEL_RECESS_FRAC = 0.04`
- `LABEL_HEIGHT_FRAC = 0.40`

Geometry is parametric: the converter builds rectangular STL boxes for each
glyph rather than loading binary STL fragments. During STL generation, trace
cells are rendered as cached ligature tiles keyed by `(tile, n, e, s, w)`, where
each direction is `1` for same-copper conduction, `0` for no copper, and `-1`
for different-copper isolation. A ligature tile first adds its local solids and
same-copper protrusions, then subtracts isolation slots and any `*` or `O`
through-hole. Cached tiles may extend past one `UNIT_MM` cell; overlaps are
intentional so neighboring same-copper tiles fuse robustly in slicers.

The persistent tile cache is a pickled dictionary at
`vox2stl/tiles/tile_cache.pickle`, written as a gzip-compressed pickle stream.
Lowercase letter tiles are stored under their single-character keys, and copper
ligatures are stored under their five-part keys. If the pickle is deleted, the
cache is rebuilt lazily; lowercase letters are loaded from pre-rendered letter
STL fragments when present, otherwise they are regenerated from the built-in
letter renderer. Cache format or geometry upgrades are handled by deleting the
cache file and letting it regenerate, or by running:

```bash
vox2stl/voxtool.py warm-tile-cache
vox2stl/voxtool.py warm-tile-cache --conf coppertape
```

Non-default CLI geometry uses an in-memory
cache so stale persisted dimensions are not reused.

Default `*` and `O` hole diameters are fixed physical dimensions, independent
of `UNIT_MM`; only the `*` pin hole is enlarged from its previous value. `*` and `O` pad outer prisms use the same outside fraction and are enlarged close to
the isolation-limited maximum so pin and leg pads keep more copper around their
holes.

Label letters are inset from cell edges by `LABEL_RECESS_FRAC` to avoid
overhang. Their embossed height is `LABEL_HEIGHT_FRAC * UNIT_MM`, starting at
the trace layer base height.

Rebuild the persistent letter tile library after changing label geometry:

```bash
vox2stl/build_letter_tiles.py
```
