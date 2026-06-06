# Pico2W Sensor HAT STL Plan

This plan describes the generated copper-tape circuit-board STL variants in
this directory. The generator source of truth is `generate_sensor_hat_stl.py`.

## Goal

Build a first-iteration 3D-printed Pico 2 W sensor HAT that acts like a
single-layer PCB for copper tape.

The printed part carries:

- A Raspberry Pi Pico 2 W through-hole footprint.
- AHT20 temperature/humidity module pads.
- 38 kHz IR transmitter module pads.
- 38 kHz IR receiver module pads.
- Raised, tapeable traces for `3V3`, `GND`, `GP4`, `GP5`, `GP14`, and `GP15`.

The top surface intentionally uses only three functional heights:

- Base: the lowest top surface for un-routed board area.
- Unconnected: mid-height collars around holes that should not receive copper.
- Trace: the highest raised conductors and pads for copper tape.

Embossed orientation labels are mid-height features, matching the unconnected
mounting-hole collars so the letters are less fragile. They do not add another
functional height.

## Variants

The generator produces two physical variants:

- `up-side`: components mount from the raised trace side. The trace side is the
  working top side, and the Pico pins enter from the flat bottom side.
- `pico-side`: components mount from the flat side. Their pins pass through all
  layers to the raised trace side. The trace-side module pin order is the same
  as `up-side`; orient the flat-side modules so their pins match that order.

Both variants keep all copper paths as a single raised trace layer. Both variants
emboss `USB` near the south USB end and emboss the variant name on the trace
side between the north mounting holes.

## Cardinal Directions And Coordinate System

All coordinates are in millimeters. View the board from the raised trace side.
In this top view:

- `+Y` is north.
- `-Y` is south.
- `-X` is west.
- `+X` is east.
- `+Z` is up from the printer bed.

The Pico 2 W USB connector is at the south end (`-Y`). The antenna end is north
(`+Y`). The USB pocket is centered near the south edge of the HAT.

In the `up-side` variant, the Pico pins enter from the flat bottom side of the
printed board and the AHT20/IR modules mount from the raised trace side.

In the `pico-side` variant, the AHT20/IR modules mount from the flat side and
their pins pass through the board to reach the raised trace side. The Pico pins
also pass through the board; clip overlong pins after assembly if needed.

## Board Envelope

The board outline is tightened around the outer through-hole edges with about
2 mm margin. The current generated board envelope is:

- West edge: about `x = -11.44`
- East edge: about `x = 11.44`
- South edge: about `y = -26.70`
- North edge: about `y = 26.70`
- Overall size: about `22.88 mm x 53.40 mm`

The Pico electrical routing stays between the Pico header rows, inside
`x = -8.89` through `x = 8.89`. The board should not grow beyond the hole-edge
margin unless a connector clearance requires it.

USB pocket:

- `x = -4.50` through `x = 4.50`
- from the south board edge to about `y = -24.80`

Pico mounting holes:

| Hole | X | Y |
| --- | ---: | ---: |
| SW | -5.70 | -23.50 |
| NW | -5.70 | 23.50 |
| SE | 5.70 | -23.50 |
| NE | 5.70 | 23.50 |

## Heights And Widths

The STL is generated Z-up.

| Feature | Z top | Notes |
| --- | ---: | --- |
| Base top | 3.175 | 1/8 inch base thickness |
| Unconnected collar top | 4.425 | Base plus 1.25 mm |
| Trace top | 6.350 | Base plus 1/8 inch raised trace |

Current horizontal dimensions:

| Feature | Size |
| --- | ---: |
| Pico through-hole diameter | 1.10 mm |
| Sensor/module through-hole diameter | 2.10 mm |
| Mounting-hole diameter | 2.40 mm |
| Signal trace width | 1.35 mm |
| Center rail width | 1.775 mm |
| Pico connected pad width | 1.70 mm square |
| Sensor/module connected pad width | 2.35 mm square |
| Mounting pad/collar width | 3.40 mm square |

All holes are through-holes through every layer that overlaps them: base,
mid-height unconnected collars, highest traces, highest pads, and orientation
labels
features if they ever overlap a hole. The sensor/module holes are approximately
twice the Pico pin-hole diameter.

Adjacent 2.35 mm sensor/module pads on the 2.54 mm pitch have about 0.19 mm
nominal edge-to-edge clearance. The two center rails are on 2.54 mm pitch and
have about 0.765 mm nominal edge-to-edge clearance.

## Pico Header Layout

The Pico header holes follow the official KiCad Pico footprint, centered on the
board coordinate origin. The west column is `x = -8.89`. The east column is
`x = 8.89`.

The west column is numbered from south to north:

| Pin | X | Y |
| ---: | ---: | ---: |
| 1 | -8.89 | -24.13 |
| 2 | -8.89 | -21.59 |
| 3 | -8.89 | -19.05 |
| 4 | -8.89 | -16.51 |
| 5 | -8.89 | -13.97 |
| 6 | -8.89 | -11.43 |
| 7 | -8.89 | -8.89 |
| 8 | -8.89 | -6.35 |
| 9 | -8.89 | -3.81 |
| 10 | -8.89 | -1.27 |
| 11 | -8.89 | 1.27 |
| 12 | -8.89 | 3.81 |
| 13 | -8.89 | 6.35 |
| 14 | -8.89 | 8.89 |
| 15 | -8.89 | 11.43 |
| 16 | -8.89 | 13.97 |
| 17 | -8.89 | 16.51 |
| 18 | -8.89 | 19.05 |
| 19 | -8.89 | 21.59 |
| 20 | -8.89 | 24.13 |

The east column is numbered from north to south:

| Pin | X | Y |
| ---: | ---: | ---: |
| 21 | 8.89 | 24.13 |
| 22 | 8.89 | 21.59 |
| 23 | 8.89 | 19.05 |
| 24 | 8.89 | 16.51 |
| 25 | 8.89 | 13.97 |
| 26 | 8.89 | 11.43 |
| 27 | 8.89 | 8.89 |
| 28 | 8.89 | 6.35 |
| 29 | 8.89 | 3.81 |
| 30 | 8.89 | 1.27 |
| 31 | 8.89 | -1.27 |
| 32 | 8.89 | -3.81 |
| 33 | 8.89 | -6.35 |
| 34 | 8.89 | -8.89 |
| 35 | 8.89 | -11.43 |
| 36 | 8.89 | -13.97 |
| 37 | 8.89 | -16.51 |
| 38 | 8.89 | -19.05 |
| 39 | 8.89 | -21.59 |
| 40 | 8.89 | -24.13 |

## Connected Pico Pins

Only these Pico header positions receive highest-layer trace pads:

| Pico pin | Net | Coordinate |
| ---: | --- | --- |
| 3 | GND | `(-8.89, -19.05)` |
| 6 | GP4 / I2C0 SDA | `(-8.89, -11.43)` |
| 7 | GP5 / I2C0 SCL | `(-8.89, -8.89)` |
| 8 | GND | `(-8.89, -6.35)` |
| 19 | GP14 / IR TX | `(-8.89, 21.59)` |
| 20 | GP15 / IR RX | `(-8.89, 24.13)` |
| 36 | 3V3 | `(8.89, -13.97)` |
| 38 | GND | `(8.89, -19.05)` |

Every other Pico header hole gets a mid-height unconnected collar. The collar
keeps the through-hole visible and supported, but it should not receive copper
tape.

## Sensor And Module Pads

All module pads are on 2.54 mm pitch and stay inside the two Pico header rows.
The module orientation is chosen to make one-layer trace routing possible
without crossing. Both variants use the same trace-side hole order. In the
`pico-side` variant, mount modules from the flat side in the orientation that
makes their pins match this trace-side order.

`up-side` AHT20 row, west to east:

| Module pin | Net | Coordinate |
| --- | --- | --- |
| SDA | GP4 | `(-6.35, -11.43)` |
| SCL | GP5 | `(-3.81, -11.43)` |
| GND | GND | `(-1.27, -11.43)` |
| 3V3 | 3V3 | `(1.27, -11.43)` |

`up-side` IR transmitter row, west to east:

| Module pin | Net | Coordinate |
| --- | --- | --- |
| DAT | GP14 | `(-3.81, 8.89)` |
| GND | GND | `(-1.27, 8.89)` |
| VCC | 3V3 | `(1.27, 8.89)` |

`up-side` IR receiver row, west to east:

| Module pin | Net | Coordinate |
| --- | --- | --- |
| OUT | GP15 | `(-3.81, 16.51)` |
| GND | GND | `(-1.27, 16.51)` |
| VCC | 3V3 | `(1.27, 16.51)` |

## Routed Nets

The HAT is a single-layer raised-trace design. There are no vias and no
crossovers. The two variants share the same electrical trace topology; they
differ by embossing and intended assembly side.

### Power Rails

Two vertical center rails run north/south between the Pico header rows:

| Net | X center | Y range | Width |
| --- | ---: | ---: | ---: |
| GND | -1.27 | -19.05 to 18.00 | 1.775 mm |
| 3V3 | 1.27 | -13.97 to 18.00 | 1.775 mm |

The 3V3 rail is fed from Pico pin 36 by a horizontal trace:

```text
(8.89, -13.97) -> (1.27, -13.97)
```

The GND rail is fed from three Pico GND pins:

```text
(-8.89, -19.05) -> (-1.27, -19.05)
(-8.89,  -6.35) -> (-1.27,  -6.35)
( 8.89, -19.05) -> (-1.27, -19.05)
```

The `up-side` module power pads sit directly on, or close to, these rails:

- AHT20 GND at `(-1.27, -11.43)`
- AHT20 3V3 at `(1.27, -11.43)`
- IR TX GND at `(-1.27, 8.89)`
- IR TX VCC at `(1.27, 8.89)`
- IR RX GND at `(-1.27, 16.51)`
- IR RX VCC at `(1.27, 16.51)`

The routing takes advantage of multiple Pico GND pins so GND can be tied into
the center rail from both sides while staying inside the Pico header rows.

### Signal Routes

GP4 to AHT20 SDA:

```text
(-8.89, -11.43) -> (-6.35, -11.43)
```

GP5 to AHT20 SCL:

```text
(-8.89, -8.89) -> (-3.81, -8.89) -> (-3.81, -11.43)
```

GP14 to IR transmitter DAT:

```text
(-8.89, 21.59) -> (-7.11, 21.59) -> (-7.11, 8.89) -> (-3.81, 8.89)
```

GP15 to IR receiver OUT:

```text
(-8.89, 24.13) -> (-5.08, 24.13) -> (-5.08, 16.51) -> (-3.81, 16.51)
```

The GP14 and GP15 lanes are separated enough for the current 1.35 mm trace
width. The generator validates that no highest-layer boxes from different nets
overlap.

## Orientation Marks And Dummy Trace

Both variants have a mid-height `USB` label between the south mounting holes,
near the USB connector pocket. This helps identify the south edge.

The trace side also has one mid-height variant label between the north
mounting holes:

- `UP` above `SIDE` on the component-on-trace-side variant.
- `PICO` above `SIDE` on the flipped, component-on-flat-side variant.

Near the northeast corner, by the Pico GND hole adjacent to GP17, the board has
a short do-nothing highest-layer raised trace. It is intentionally unconnected
and only acts as a local physical marker/test feature.

## Fabrication Notes

Print the STL with the flat base on the bed and the raised conductors facing up.
After printing:

1. Choose the correct variant for the side where the modules will mount.
2. Insert pins through the board so they pass completely through every layer.
3. Apply copper tape only to the highest pads and traces.
4. Leave mid-height collars bare.

The current design assumes modules are wired for 3.3 V power. Confirm IR module
signal voltage behavior before using any 5 V-powered IR board with Pico GPIO.

## Regeneration

From `thermo/onboard/hardware/pico2w`:

```bash
make hat-stl
```

Expected variant outputs:

- `hat/thermo-pico2w-sensor-hat-v1-up-side.stl`
- `hat/thermo-pico2w-sensor-hat-v1-pico-side.stl`

The legacy `hat/thermo-pico2w-sensor-hat-v1.stl` may be kept as an alias of the
`up-side` variant for compatibility with earlier notes.

The generator writes ASCII STL. The file is large because the dependency-free
mesh generator emits explicit triangles for the gridded plate, hole walls,
mid-height collars, and raised traces.
