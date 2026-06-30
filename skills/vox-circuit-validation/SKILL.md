---
name: vox-circuit-validation
description: Use when working on vox2stl/check_vox.py, text .vox circuit validation, trace shorthand, pad connectivity, or thermo Pico2W HAT voxel circuits.
---

# VOX Circuit Validation

## Domain Model

- In Pico/HAT `.vox` diagrams, pins with the same source name are inherently the same electrical net. Repeated labels such as `GND` are not separate copper features that must be joined on the printed trace; they refer to the same source net by construction.
- Do not infer a failure merely because repeated same-named header pins are not connected by printed copper in the trace layer.
- `O` device-leg pads do not connect directly to adjacent `O` pads, but `O` does connect to trace arms from any side. Valid examples include horizontal `-O-` and vertical `|` over `O` over `|`.
- Alias glyphs such as `alias V -> | = VCC` and `alias G -> | = GND` declare net membership while behaving electrically like their target trace glyph.
- Inline notes such as `.c4 = VCC` declare net membership for the referenced cell.
- Correctness criterion: each flood-filled copper component has one net label set from aliases, inline `.cN = NET` notes, net intents, and pin labels. All labels on that component must be the same, and a labeled component must reach at least one source pin with that same net.
- A same-named source pin elsewhere does not rescue a floating labeled copper component.
- `VCC` is always a net alias for `3V3`; treat them as the same canonical net.
- A `.vox` file may contain only a `trace` layer for circuit validation. Add a `base` layer only when testing trace/base pin-label agreement or pad-shape agreement.

## ASCII Trace Shorthand

Map direct shorthand to box-drawing semantics as follows:

- `<` -> `BOX_T_LEFT` (U+2524), arms N/W/S.
- `>` -> `BOX_T_RIGHT` (U+251C), arms N/E/S.
- `^` -> `BOX_T_UP` (U+2534), arms W/N/E.
- `T` -> `BOX_T_DOWN` (U+252C), arms W/S/E.

Use arm semantics, not vague visual names, when reasoning about these characters.

## Lesson From The Up-Side Debugging Session

- The user asked for a test that embeds the current `up-side.vox` trace layer verbatim and expects the validator to fail by simply running the validator.
- Do not respond to that request by inventing new validation rules first. Add the requested failing fixture, run it, and let the failure guide the next change.
- During analysis, distinguish between source-net identity and printed copper connectivity. Same-labeled source pins are already electrically identical; printed traces should be checked for shorts/splits among declared trace endpoints and device pads, not for reconnecting repeated source pins.
- In the current `up-side.vox` trace-layer exercise, repeated `GND` source labels were not the circuit failure. The suspicious failure was on the GP4/AHT20 SDA row: the trace row labels the right source pin as `GP35` and routes the c6 leg to that right pad, while the base diagram labels that right source pin `ADCV`.
