# REPL design sketch (imgcomp visual bedrock)

Status: design only. Language surface and host UI remain unresolved on the
ticket; this sketch stays host-agnostic where possible and treats today's
`LivePreview` (Tk) as one adapter.

Goals from the ticket: ductile, responsive edit-eval-draw; caching aimed at
~30fps for drag/animation; pedagogy from `pedagogy-brief.md`.

## Loop

```
+-- learner edits text (or teacher live-codes)
v
eval in a restricted namespace  -->  on success: update bindings + scene root
  | fail                          -->  keep prior scene; show warm error
  v
invalidate cache entries touched by changed bindings
  v
render (full or partial) into Surface
  v
present (Tk / PNG / other adapter)
  v
input (pick / drag) --> optional mutate bindings --> invalidate --> render
```

Cadence:

- *Eval path* (on Enter / Run): correctness and warmth first; <100ms is a
  nice-to-have for small scenes, not a hard gate.
- *Frame path* (drag, animation tick): target ~33ms/frame via cache hits.
  Misses may drop frames; never tear down the last good frame.

## Namespace and scene root

The REPL owns:

| Name | Role |
|------|------|
| `W`, `H` | viewport size (ints) |
| `scene` | current `Scene` (shape or list), back-to-front |
| `comp` | `NaiveCompositor(W, H)` (or future faster compositor) |
| learner bindings | e.g. `ball`, `bg` -- values are usually `Shape`s |

Eval does **not** replace the whole process. It `exec`/`eval`s against a dict
that already contains helpers (below). Successful eval may assign `scene = ...`
or mutate objects in place; both must mark dirty.

Failed eval: leave `scene` and bindings unchanged; surface error text with
optional last pick coords.

## Minimal learner API (v0)

Keep the typed surface small. Everything else is power-up later.

```text
# constructors
circle(r) -> Shape
rect(hw, hh) -> Shape
oval(rx, ry) -> Shape
color(shape, r, g, b, a=255) -> Shape
move(shape, x, y) -> Shape          # Translate
turn(shape, degrees) -> Shape       # Rotate
stretch(shape, sx, sy) -> Shape

# scene
show(*shapes) -> None               # sets scene = list(shapes) back-to-front
add(shape) -> None                  # append on top
clear() -> None                     # empty scene (keep viewport)

# probe / debug (teaching tools)
pick(vx, vy) -> name or None        # topmost binding under viewport pixel
sample(vx, vy) -> RGBA              # composed color at pixel
```

Fluent imgcomp methods remain available for the teacher; v0 wrappers exist so a
learner can stay in verb-noun English.

Unresolved: whether `circle` is Python-callable syntax or a smaller toy
language that compiles to the same calls.

## Caching model (toward 30fps)

Naive per-pixel walk is fine for tiny teaching canvases and rare evals. Drag
and animation need reuse.

### Layer cache (primary)

- Treat each top-level entry of the scene list as a *layer*.
- Cache: `layer_id -> ArraySurface` of the full viewport contribution *alone*
  (transparent where the layer does not hit), plus a content hash / revision.
- Composite cached layers back-to-front with `src_over` (cheap relative to
  re-sampling SDF trees).

Invalidate layer `i` when:

- that list entry's object identity or deep revision changes;
- a binding used to build that entry changes;
- viewport size changes (flush all).

### Object revision

Each wrapper/leaf carries or inherits a `rev` int (or hash of parameters).
Mutating `Translate.tx` bumps rev. Eval that rebinds `ball = move(...)`
creates a new object -> new rev -> that layer misses cache.

### Dirty rectangles (secondary, optional in spike)

When only a translated opaque blob moves, re-render union of old and new AABB
into an otherwise cached backdrop. Defer until layer cache is proven; AABBs for
rotated SDF unions are fiddly.

### What we will not cache in v0

- Inside a single animated SDF boolean tree every frame (must resample).
- Across viewport resizes.

### Budget sketch (VGA-ish teaching size)

Example: 320x240, 5 layers, one layer moving:

- Miss one layer: resample 320*240 hits for that layer only.
- Hit four layers: four fullscreen src_over passes from cached RGBA.

That is the intended path to "feels like 30fps" on CPU without numpy.

## Host adapters

| Adapter | Present | Input | Notes |
|---------|---------|-------|-------|
| Tk `LivePreview` | PhotoImage | mouse -> `dispatch_event` | Already in tree; fine for spike |
| Headless PNG | write file / open viewer | none or separately | Good for tests and Emacs workflows |
| Future | -- | -- | Same REPL core; swap presenter |

The REPL core must not import Tk at module level; the Tk adapter depends on the
core.

## Error warmth (non-negotiable for pedagogy)

On exception during eval:

1. Keep last good `scene` displayed.
2. Show exception type + message.
3. If the failing expression involved a name, print its current binding type.
4. Optional: last pick target name under the cursor.

Never clear the canvas as an error signal.

## File layout (proposed, for the spike)

```text
imgcomp/
  repl/
    __init__.py      # public: ReplSession, run_line
    session.py       # namespace, eval, scene root, dirty tracking
    api_v0.py        # circle/rect/show/...
    cache.py         # layer cache + composite
  live.py            # existing; later: LivePreview.from_session(...)
  docs/
    pedagogy-brief.md
    primitive-map.md
    repl-design.md   # this file
```

## Spike acceptance (next WorkItem)

1. `ReplSession` can `run_line` to build a 2-3 layer scene headlessly.
2. Layer cache: moving one `Translate` invalidates one layer; others reuse.
3. Microbench or test: repeated frames with one moving layer faster than full
   naive re-render (assert speedup ratio or time budget on a fixed size).
4. No Tk required for tests; optional demo hook via existing `LivePreview`.

## Product decisions (descoped at merge)

Deferred out of this ticket's acceptance; spike ships a Python-exec v0 API and
headless render. Host (Tk LivePreview vs PNG) and lesson coupling can be chosen
in a follow-on without blocking the layer-cache REPL core.
