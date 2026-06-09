---
name: ascii-circuit-layout
description: >-
  Rules for ASCII tile-based circuit layout in thermo hardware HAT .vox files.
  Use when editing trace layers, routing nets, validating HAT voxel diagrams, or
  regenerating board-specific hat artifacts under thermo/onboard/hardware/*/hat/.
---

# ASCII Circuit Layout

One grid cell is one character and one physical tile. For Pico and the initial
ESP32-S3 DevKitC work, the default tile pitch is 2.54 mm. Adjacency is north,
east, south, and west only; diagonal cells never connect.

Read or write `# scratch` comments at the end of a `.vox` file between routing
steps. Re-read the file after each step.

## File Ownership

- Shared layout rules and validation live in `thermo/onboard/hardware/`.
- Board-generated or board-specific artifacts live in leaf `hat/` dirs, such as
  `thermo/onboard/hardware/pico2w/hat/` and
  `thermo/onboard/hardware/esp32s3_devkitc1/hat/`.
- A board profile owns header labels, expected pin columns, module leg columns,
  and physical header spacing.

## Characters

| Char | Role |
| --- | --- |
| `.` | Empty / air, no copper |
| `X` | Solid substrate, base layer only |
| `*` | Host board header through-pad |
| `O` | Device leg through-pad |
| `a`..`z` | Embossed uppercase labels, not copper |
| `-` | Horizontal trace, east-west |
| `|` | Vertical trace, north-south |
| box corners | Corner traces |
| box T junctions | Three-way trace junctions |
| `+` or box cross | Four-way trace intersection |

Base layers use `X`, `*`, and `O`. Trace layers use `.`, `*`, `O`, lowercase
labels, straight traces, corners, T junctions, and four-way intersections.

## Connection Rules

Straight traces protrude slightly along their axis so they can meet the next
tile. Pads are recessed so adjacent pads do not connect without an explicit
trace. Straight traces are recessed perpendicular to their axis.

Connect pairs:

- `--` connects horizontally.
- Two stacked `|` cells connect vertically.
- `-*` and `*-` connect a horizontal trace to a header pad.
- `-O` and `O-` connect a horizontal trace to a device leg pad.
- Rotated vertical equivalents connect the same way.
- Corners connect only on their two drawn arms.
- T junctions connect only on their three drawn arms.
- `+` connects north, east, south, and west.

No-connect pairs:

- `OO`, `**`, `*O`, and `O*` do not connect.
- `*|`, `|*`, `O|`, and `|O` do not connect horizontally.
- Side-by-side `||` cells do not connect.
- `-|`, `|-`, `+|`, and `|+` do not make horizontal turns.

Use a corner glyph for a turn. Do not put `-` beside `|` and expect a bend.
Do not merge unrelated nets by sharing a `+`, T junction, or vertical trunk.

## Iterative Trace Workflow

The base layer must exist and be user-approved before trace work. For a new HAT
variant, stop after base placement and wait for approval before routing traces.

Before routing, prime anchors:

1. Copy every base-layer `*` used by the design onto the trace layer.
2. Copy every base-layer `O` onto the trace layer.
3. Fill all other trace cells with `.`.
4. Add row comments documenting module leg order, column choices, and intended
   GPIO or power connections.
5. Add `# scratch` or `# todo` comments at the bottom with the route plan.
6. Run `vox2stl/check_vox.py` for the target `.vox`.

Route one functional group per pass. Power rails usually come first, then one
module signal group per pass. After every pass:

- Re-read the `.vox` file and bottom notes.
- Add only the glyphs for the current group.
- Run anchor analysis mentally: live copper must join two or more anchors.
- Run `vox2stl/check_vox.py`.
- Update `# scratch` or `# todo`.
- Stop for user approval before the next iteration.

## Trace Intents

After the trace layer, add a `# trace intents` block. The checker flood-fills
copper and validates declared nets and disjoint nets:

```text
# trace intents
# net SDA GP4.c1 GP4.c3
# net SCL GP5.c1 GP4.c4
# disjoint SDA SCL
```

Use `LABEL.cN` for endpoints. Use `LABEL:N.cN` when a row label appears more
than once, where `N` is the 1-based occurrence.

Trace-row comments may also assert expected nets for module legs with
`.cN = NET`. The checker flood-fills the cell and fails if it does not reach
the declared `# net NET` component.

## Layout Checks

- The checker passes for the board leaf `.vox` file.
- Trace-layer pads match base-layer pads exactly.
- Row comments document module legs on the actual module row.
- Bottom scratch notes record what was done and what comes next.
- No unrelated nets share a live connected component.
- No orphan trace cells remain after anchor analysis.
