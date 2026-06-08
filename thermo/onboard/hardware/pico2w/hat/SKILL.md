---
name: ascii-circuit-layout
description: >-
  Rules for ASCII tile-based circuit layout in thermo Pico2W HAT .vox files.
  Use when editing trace layers, routing nets, or regenerating hat voxel
  diagrams in thermo/onboard/hardware/pico2w/hat/.
---

# ASCII circuit layout (Pico2W HAT vox)

One grid cell = one character = one 2.54 mm tile. Adjacency is east, west, north,
south only (no diagonals). A "pair" is two orthogonally adjacent cells.

Read or write `# scratch` comments at the end of a `.vox` file between routing
steps. Re-read the file after each step.

## Tile geometry (why connect / no-connect)

- Straight traces (`-`, `|`) **protrude** slightly past their cell edge along
  their axis so they can meet the next tile.
- Pads (`*`, `O`) and empty (`.`) are **recessed** relative to traces.
- `|` and `-` are **very recessed** perpendicular to their axis.

Connection is decided by protrusion vs recess at the shared edge, not by net name.

## User rules (current glyphs)

-- connect

| connect. henceforth all rotations will connect. - and | are rotations, and
similarly for corners.

`-*` / `*-` connect. -+ connect, ++ connect. || do not connect. The general idea is that
straight line "protrude" somewhat out of their boxes, but pads like `*` and `O` are
recessed so that OO does not connect, but -O does. lines | and - are VERY
recessed, and -| and +| DO NOT connect.

## Characters

| Char | Role |
| --- | --- |
| `.` | Empty / air (no copper) |
| `X` | Solid substrate (base layer only) |
| `*` | Pico pin through-pad |
| `O` | Device leg through-pad |
| `a`..`z` | Embossed uppercase labels, not copper |
| `-` | Horizontal trace (E-W) |
| `|` | Vertical trace (N-S) |
| `┌` / `┐` / `└` / `┘` | Corner traces |
| `├` / `┤` / `┬` / `┴` | T junctions |
| `┼` / `+` | Four-way intersection (N/E/S/W) |

Base layer uses `X`, `*`, `O`. Trace layer uses `.`, `*`, `O`, lowercase
labels, `-`, `|`, corners, T junctions, and four-way intersections.

## Connect pairs (yes)

Treat rotated forms the same way (`-` and `|` are rotations of each other).

| Pair | Meaning |
| --- | --- |
| `--` | Horizontal trace continues E-W |
| two stacked `|` (same column) | Vertical trace continues N-S |
| `-*` | Horizontal trace into Pico pad |
| `-O` | Horizontal trace into device leg pad |
| `-┐`, `-┘`, `-┬`, `-┤`, `-┼` | Horizontal into a tile with a west arm |
| `|` stacked with `┐`, `┌`, `├`, `┤`, or `┼` | Vertical into a tile with a north/south arm |
| corner rotations | Corner tiles connect only on their two drawn arms |
| T rotations | T tiles connect only on their three drawn arms |

Pads accept a trace from the recessed side: `-O`, `-*` / `*-`, and the vertical
equivalents (trace north or south of pad, same column).

## `+` vs `|` (different behavior)

- `|` = straight vertical segment only. Use stacked `|` in one column for a
  straight run. Never use `+` where a plain `|` would do.
- Corners (`┌┐└┘`) are preferred for turns.
- T junctions (`├┤┬┴`) are preferred for three-way joins.
- `+` or `┼` is only for a true four-way intersection. A lone `+` does not
  replace a vertical trunk or a corner.

## No-connect pairs (no)

| Pair | Why |
| --- | --- |
| `OO` | Adjacent recessed leg pads |
| `**` | Adjacent recessed pin pads |
| `*O` / `O*` | Pad-to-pad without a trace between |
| `*|` / `|*` | Pad beside vertical bar; not `-*` / `*-` |
| `||` | Adjacent vertical traces in adjacent columns (parallel, side by side) |
| `-|` | Perpendicular recess: horizontal meets vertical without `+` |
| `+\|` / `\|+` | Horizontal neighbors: `+` E-W arm does not meet `|` N-S arm |

**Do not** place `-` west of `|` (or `|` north of `-`) in adjacent cells and
expect a turn. Put the right corner glyph at the corner cell instead.

**Do not** merge unrelated nets by sharing a `+` or a `|` column. One trunk per
net unless they are the same net.

## Corner: left-to-bottom from a pin

From a west pin pad, route east then south:

```text
GP15  .*.-┐......   row N:   *- into -, then -┐ into turn cell at c3
GP14  .*..|......   row N+1: | continues GP15 at c3 (GP14 pad at c1 only)
GND   ...||||...   row N+2: | continues south; separate column for GP14
```

Rules for that pattern:

- Row N uses `.*.-┐` at c1-c3: `*-`, then `-┐`. The `┐` owns the southbound arm.
- Row N+1 continues the **same net** with `|` at the same column; vertical runs use `|`.
- Row N+2 keeps using `|` for the straight vertical run.
- A different net on the same row must leave a **buffer column** (`.`) between
  any `-`/`+` from one pin and another pin's trace. Adjacent `-+` across nets
  is a short.

Wrong (same row as GP14 pin):

```text
GP14  .*.|+......   *| does not connect; |+ does not connect; pin isolated
```

Wrong (horizontal neighbor `|` used as a corner):

```text
GP14  .*.|+......   c2 `|` does not connect horizontally into c3 `+`
```

Wrong (straight vertical):

```text
GP12  ..+|.|....    + at c2 is not a vertical trunk; use | at c2
```

Correct GP14 on c6 with GP15 on c3 (buffer at c4):

```text
GP14  .*..|.-┐..   c1=* pad; c3=| GP15 trunk; c5-c6 GP14 -┐ into c6
```

## Iterative trace layer workflow

The base layer must exist and be user-approved before any trace work. For a new
hat variant that is an iterative step on its own; do not edit trace until base
is signed off.

One trace layer per pass (`layer trace` in the `.vox` file). Work in numbered
iterations. **Stop after each iteration and wait for the user** to say go ahead,
tweak, or `next iteration`. Do not run ahead.

### File conventions

- Match base layer row labels and geometry exactly.
- Use `#` comments above the trace layer for module placement and leg columns.
- Keep agent TODO, net plan, and backtrack notes in `# scratch` / `# todo`
  comments at the **bottom of the file** (state memory between iterations).
- Re-read the whole `.vox` file at the start of every iteration.

### Column reference (up-side)

Design window columns (west to east):

| Col | X mm | Role |
| --- | ---: | --- |
| c1 | -8.89 | West Pico pins |
| c2 | -6.35 | |
| c3 | -3.81 | |
| c4 | -1.27 | signal / routing (up-side shifted) |
| c5 | 1.27 | GND rail (up-side shifted) |
| c6 | 3.81 | 3V3 rail (up-side shifted) |
| c7 | 6.35 | |
| c8 | 8.89 | East Pico pins |

### Iteration -1: prime pads only

Before iteration 0, lay out **only** anchors on the trace layer:

1. Copy every base-layer `*` you will use onto the trace layer (same cells).
2. Copy every base-layer `O` onto the trace layer (same cells).
3. Fill all other trace cells with `.`.
4. Add comments on the **row where the module legs are**, west-to-east leg
   order, column for each leg, and which GPIO pins connect. Do not put module
   notes on a GPIO-only row above/below. Example:

```text
# Module IR RX row GP13 (y=16.51): c4=OUT, c5=GND, c6=VCC
# Module IR TX row GP10 (y=8.89):  c4=DAT, c5=GND, c6=VCC
GP4   ... ADCV  AHT20 c3=SDA c4=SCL c5=GND c6=3V3; I2C0 GP4/SDA pin6 GP5/SCL pin7
```

(`GP5` row has the SCL header pad only; all AHT20 detail stays on `GP4`.)

5. Write initial `# todo` at file bottom: GPIO plan, rail column picks, module
   order for later iterations, known risks.
6. Run `check_vox.py` (asserts exact `*`/`O` columns per row). On trace rows with
   routing notes, use parseable `cols cN=TOKEN` assertions (`*-`, `-*`, `|`,
   `-`, corners, T junctions, and intersections); the checker verifies each
   against the diagram. Show the user.
   **Wait for go ahead.**

No trace glyphs yet (`-`, `|`, corners, T junctions, intersections).

### Iteration 0: power rails

Goal: shared GND and 3V3 columns linked vertically across module rows, then tied
to the Pico header.

**Power placement heuristic** (backtracking is expected; first pick may fail):

- You usually have **more GND legs than V legs**. Place **3V3 (V) first**, then
  GND beside it.
- Default leg order west-to-east: signal(s), **GND**, **VCC/3V3** -- but AHT20
  uses SDA, SCL, GND, 3V3 (GND before V in that row).
- On **up-side** (shifted layout): **c5 = GND rail**, **c6 = 3V3 rail**; **c2** is
  buffer west of module legs. Pico-side uses its own column map.
- Run `|` north-south in those columns through every module row that has an `O`
  on that net. Leg `O` cells sit on the rail column and replace `|` at that row.
- Leave `OO` gaps between unrelated signal leg pads; only GND/V legs touch rails.
- Tap **one** east or west `3V3` header `*` into the c6 rail with the right T
  glyph on the rail.
- Tap **one** convenient `GND` header `*` into the c5 rail (often a far-corner
  GND pin to keep signal columns clear) with the right T glyph on the rail.
- Run anchor analysis. Run `check_vox.py`.
- Update bottom `# todo` with rail choices, taps used, and what blocks iteration 1.
- Show the user. **Wait for go ahead or tweak.**

### Iteration 1, 2, 3, ...: one signal module per pass

Each iteration routes **one module's signal leg(s)** (not GND/VCC -- those are on
rails from iteration 0 unless a rework is needed).

Signal GPIO choice:

- Except for special-purpose pins such as GND, V, and fixed power/control pins,
  GPIOs are interchangeable for this hat.
- Prefer the closest suitable GPIO that gives a clean route unless the user pins
  a specific assignment.

Order suggestion for up-side (adjust if user says otherwise):

1. AHT20 (GP4 SDA, GP5 SCL)
2. IR RX (nearest clean GPIO; usually GP13 OUT)
3. IR TX (nearest clean GPIO; usually GP10 DAT)

Per iteration:

1. Re-read file and bottom notes.
2. Add trace glyphs only for this module's signal(s).
3. Connect header `*` to signal `O` using `-` for horizontal, `|` for vertical,
   corners for turns, T glyphs for tees, and `+`/`┼` only for four-way crossings.
   Leave a buffer column between unrelated nets on the same row.
4. GPIO reassignment is cheap if the column fight is too tight.
5. Run anchor analysis for the new net(s).
6. Run `check_vox.py`.
7. Update bottom `# todo`: what is done, what is next, backtrack ideas.
8. Show the user. **Wait for approval or tweak.**

If anchor peel removes the new work or leaves a pin floating, treat the iteration
as failed: revert that signal in the diagram, note the failure in `# todo`, and
ask the user before retrying.

### When the trace layer is complete

All signal anchors must survive anchor analysis connected to their header `*`.
Power rails must join at least one `3V3` and one `GND` header pad. No unrelated
shorts. Final `check_vox.py` pass.

## Anchor analysis (find broken routes)

Pads anchor copper. A trace run is **live** only when it joins **two or more
anchors** (`*`, `O`, or a pad on a power rail you intentionally tied) through
legal connect pairs. Use this peel pass after every routing edit.

### Anchors

- `*` = Pico pin anchor for that net.
- `O` = device leg anchor for that net.
- A rail tap counts as an anchor only after an `*`/`O` or another live trace
  reaches it by legal rules.

Trace tiles (`-`, `|`, corners, T junctions, and intersections) are not anchors.
They are provisional until they sit between anchors.

### Peel algorithm

Repeat until a full pass removes nothing:

1. Scan every trace glyph cell.
2. For each **open arm** (N, E, S, or W), ask: does the neighbor connect by the
   connect-pair rules? Treat `.` and illegal pairs (`*|`, `|+`, `OO`, etc.) as
   open.
3. If **all** open arms are open (isolated tile), delete it: set the cell to `.`.
4. If **some** arms are open and **some** are live, this cell is a dead end.
   Delete it: set the cell to `.`.
5. Pads are never deleted. Re-check neighbors after each deletion.

When stable, re-run from step 1 on the updated grid until no trace cell is removed.

### Read the result

| After peel | Meaning |
| --- | --- |
| Pin `*` beside only `.` | Pad never joined a net (`*|` mistake). |
| Leg `O` beside only `.` | Module pad floating; missing `-O` approach. |
| Two anchors, no path | Net broken (wrong corner/T orientation or bad neighbor pair). |
| Trace tile left | Orphan copper; should have been pruned -- recheck connects. |
| Two pins on one component | Short; unrelated anchors share a live path. |

A live GP15 run, for example, must survive peel with a path from row-1 `*` to
row-4 `O` (OUT). If peel eats the column above OUT back to `.`, the turn failed
(wrong corner orientation or `|+` on the same row).

Work by net: finish one signal, run anchor analysis, then start the next.

## Layout checks (every iteration)

- `check_vox.py` passes, including **pin column assertions** (see below).
- Pads match approved base layer holes at exact columns.
- Module comments and leg columns documented on the leg row.
- Bottom `# todo` updated with state for the next pass.
- No `||` short between unrelated nets in adjacent columns.
- No `-|`, `+|`, or `|+` as horizontal corner pairs; use the correct corner glyph.
- No `*|` beside a pin expecting a join without `-` west of the pad.
- Vertical runs use stacked `|`; corners use `┌┐└┘`; tees use `├┤┬┴`;
  `+`/`┼` only for four-way crossings.
- Anchor analysis (peel pass) on the trace layer.
- `check_vox.py` passes.
- User approved this iteration before starting the next one.

### Trace intents (`check_vox.py`)

After the trace layer, add a `# trace intents` block. The checker flood-fills
copper using SKILL connect rules and validates declared nets.

```text
# trace intents
net SDA GP4.c1 GP4.c3
net SCL GP5.c1 GP4.c4
net GND GND:2.c1 GP13.c5 GP10.c5 GP4.c5
net 3V3 GP3.c8 GP13.c6 GP10.c6 GP4.c6
disjoint SDA SCL
disjoint SDA GND
```

- `net NAME ROW.cN ...` -- every endpoint must lie in one connected component.
- `disjoint A B` -- those nets must not share copper.
- Duplicate row labels: `GND:2.c1` is the second `GND` row in the trace layer
  (1-based occurrence).

Also fails when a horizontal bridge over `OO` module legs vertically contacts
both legs below. A bridge over adjacent legs is allowed when the bridge tile over
the unrelated leg is a no-contact tile for that direction, for example `-` over
an `O` below; only the intended landing tile should contact its leg.

Row-level `cols cN=TOKEN` checks glyphs only; intents check connectivity.

### Pin column self-check (`check_vox.py`)

For each labeled row, every `*` and `O` must be at the exact design-window
column expected for that variant. Trace-layer pads must match base-layer pads
cell for cell.

**up-side** module legs (header `*` always at c1 and c8):

| Row | Leg columns |
| --- | --- |
| GP13 IR RX | c4=OUT, c5=GND, c6=VCC |
| GP10 IR TX | c4=DAT, c5=GND, c6=VCC |
| GP4 AHT20 | c3=SDA, c4=SCL, c5=GND, c6=3V3 |

**pico-side** (mirrored across X=0):

| Row | Leg columns |
| --- | --- |
| P17 IR RX | c4=OUT, c5=GND, c6=VCC |
| P14 IR TX | c4=DAT, c5=GND, c6=VCC |
| P6 AHT20 | c4=SDA, c5=SCL, c6=GND, c7=3V3 |

If validation reports `O columns [3] != expected [2, 3, 4, 5]`, a leg is on the
wrong column (common mistake: shifting the whole module west by one cell).

`check_vox.py` also prints **warnings** (not failures) for horizontal `*O` / `O*`
adjacency on the base layer.

**up-side:** header `*` at c1 beside a module `O` at c2 (e.g. GP4 `*O`) is fixed by
shifting module legs and center rails **one column east** (AHT20 to c3-c6, IR to
c4-c6, GND rail c5, 3V3 rail c6). That opens c2 as routing buffer west of the
first leg.

**pico-side:** separate mirrored geometry; east-edge `O*` (e.g. P6 c7-c8) is not
the same problem and may need a different remedy. Do not assume the up-side shift
applies.

## Examples

Wrong (shorts GP14 and GP15 on one `+`):

```text
GP15  .*++......   both pins hit same c2 +
GP14  .*++......
```

Wrong (broken corner on GP14 row):

```text
GP14  .*.|+......   pin not on net; |+ does not connect
```

Wrong (`+` where `|` trunk belongs):

```text
GP12  ..+|.|....    c2 must be | for a straight GP14 trunk
```

Use `....|||...` for a straight c6 trunk past the module rows.
