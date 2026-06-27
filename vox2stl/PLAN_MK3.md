# vox2stl MK3 Plan: Direct 3MF With Materials

## Goal

Move from `.vox -> STL` toward `.vox -> 3MF` so the same text layout can carry
both geometry and material intent. The target is a colored 3MF where substrate,
insulator fill, conductor traces, labels, and debug marks can be distinct
materials or colors instead of being fused into one anonymous STL mesh.

The important design change is to stop treating one `.vox` character as one
single-height solid. Each glyph should emit one or more explicit Z bands. For
example, an `O-` connection can be printed as color/material 1 for 1.0 mm as
insulator support, then the same XY footprint can be printed as color/material 2
for 0.5 mm as conductor.

## Feasibility

This is feasible without adding heavy CAD dependencies.

3MF is a zip package containing XML parts. A minimal model package needs
`[Content_Types].xml`, `_rels/.rels`, and `3D/3dmodel.model`. Geometry is still
stored as triangular meshes: vertices plus triangles, much like the current STL
writer already produces.

3MF also supports resource properties for materials and colors. The conservative
path is to create separate mesh objects for each material/color and assign one
property to each object. That is simpler than per-triangle coloring and is more
likely to survive slicer import/export behavior. A later version can use 3MF
Materials Extension `colorgroup` properties on individual triangles, but object
per material should be the first implementation.

Expected compatibility:

- Viewers should show distinct colors when object materials or base materials
  include display colors.
- Slicers may treat colors as display-only unless the printer/material workflow
  maps them to real extruders, filaments, or tool changes.
- The 3MF package can still be useful before multi-material printing because the
  color split makes inspection much easier than STL.

## New Units

Replace single `UNIT_MM` thinking with explicit XY and Z units:

- `UNIT_XY_MM`: grid pitch for columns and rows, currently 2.54 mm.
- `UNIT_Z_MM`: vertical quantum for layer heights, for example 0.25 mm or
  0.50 mm.

Existing fractional XY constants still make sense, but their names should be
clear:

- `TRACE_WIDTH_XY_FRAC`
- `PIN_HOLE_DIAMETER_XY_FRAC`
- `LEG_HOLE_DIAMETER_XY_FRAC`
- `LABEL_RECESS_XY_FRAC`

Z heights should stop being fractions of the XY pitch unless that is truly what
we want:

- `SUBSTRATE_Z_UNITS`
- `INSULATOR_CAP_Z_UNITS`
- `CONDUCTOR_Z_UNITS`
- `LABEL_Z_UNITS`

This lets the board pitch remain 2.54 mm while conductor thickness can be tuned
in normal print-layer terms.

## Material Model

Define a small material table in the `.vox` file or in a profile loaded by the
converter:

```text
# material id name        color
material 1  substrate   #303030
material 2  insulator   #d8d8d8
material 3  conductor   #b87333
material 4  label       #ffffff
material 5  debug_grid  #0066ff
```

The names are design intent. The colors are sRGB display colors for viewers and
slicers. A slicer may ask the user to map these to actual printer materials.

## Explicit Z Bands

Add a Z schedule that maps source layers and glyph classes to height ranges and
materials. One possible syntax:

```text
# UNIT_XY_MM=2.54
# UNIT_Z_MM=0.25

zband substrate    material=1 z=0..12 source=base   chars=X*O
zband insulator    material=2 z=12..16 source=trace  chars=*O-|+corners
zband conductor    material=3 z=16..18 source=trace  chars=*O-|+corners
zband labels       material=4 z=18..20 source=trace  chars=a-z
```

That example means:

- Substrate is 12 Z units = 3.0 mm.
- Insulator under the trace pattern is 4 Z units = 1.0 mm.
- Conductor cap is 2 Z units = 0.5 mm.
- Labels are 2 Z units = 0.5 mm above the conductor or trace top.

The key point is that the same source glyph can be emitted into multiple Z bands
with different materials. `O-` is not "one object"; it is an XY footprint plus a
vertical stack of material bands.

## Geometry Strategy

Keep the current connectivity rules as the source of truth. The glyph parser
should still decide which arms connect and where isolation gaps are required.
Only the emission target changes.

Recommended first implementation:

1. Parse `.vox` into logical cells exactly as today.
2. Expand each cell into one or more `SolidPiece` records:
   - XY footprint polygons or boxes.
   - `z0_mm`, `z1_mm`.
   - `material_id`.
   - optional metadata such as source layer, glyph, row, and column.
3. Group pieces by `material_id`.
4. Mesh each material group separately.
5. Write one 3MF object per material group, each with object-level material or
   color assignment.

This avoids per-triangle material bookkeeping at first. It also makes it easy to
export debug 3MF files where substrate, conductor, labels, and grid marks can be
hidden or recolored independently by slicer object controls.

## 3MF Writer Shape

Add a new writer beside the STL writer:

```text
vox2stl/vox23mf.py
```

or add `--format 3mf` once the implementation is stable. The writer can use only
Python standard library modules:

- `zipfile` for the package.
- `xml.etree.ElementTree` for model XML.
- existing mesh generation code for vertices and triangles.

Minimal package parts:

```text
[Content_Types].xml
_rels/.rels
3D/3dmodel.model
```

The model should contain:

- `<resources>` with material/color resources.
- one `<object>` per material group.
- each object mesh with vertices and triangles.
- `<build>` items referencing those objects.

For first pass, use base materials with `displaycolor`. If slicer support is
weak, test the Materials Extension `colorgroup` path next.

## Open Questions

- Which slicer should be the compatibility target: Bambu Studio, PrusaSlicer,
  OrcaSlicer, or all three?
- Do we need true multi-material print instructions, or is visual color enough
  for inspection and manual filament/tool mapping?
- Should conductor geometry overlap insulator geometry, or should conductor sit
  on top with shared XY boundaries but separate Z ranges?
- Should holes cut through every Z band, or should some bands intentionally
  bridge/cap around holes?
- Should labels be their own material, or just conductor/insulator color on top?

## Risks

- Display colors in 3MF do not guarantee a physical material assignment.
- Some slicers may merge same-position objects or reorder object/material data.
- Per-triangle color is more compact for mixed objects, but it is also more
  fragile across slicers than separate material objects.
- Multiple Z bands can accidentally create coincident faces between materials.
  Prefer exact stacked Z ranges with no overlap, or a tiny intentional overlap
  only after slicer testing proves it is needed.

## Suggested Next Experiment

Create a tiny proof of concept before porting the full HAT:

```text
layer base (0, 4, 2)
XXXX
XXXX

layer trace (0, 4, 2)
O---
....
```

Emit it as:

- substrate object: black/gray, `z=0..3.0`.
- insulator trace footprint: white, `z=3.0..4.0`.
- conductor trace footprint: copper, `z=4.0..4.5`.

Open the 3MF in the target slicer and verify:

- separate colors are visible;
- separate objects/materials survive import;
- holes and trace arms still match `.vox` connectivity;
- no unexpected merged or missing surfaces appear.

If that works, MK3 can reuse nearly all current `.vox` routing logic and replace
only the final mesh grouping/writer stage.
