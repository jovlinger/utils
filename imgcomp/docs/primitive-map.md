# imgcomp primitives -> learner concepts

Companion to `pedagogy-brief.md`. Maps the library the REPL sits on to words a
~12yo (and teacher) can say out loud while pointing at the screen.

Coordinate note: imgcomp is *center-based*. Local (0, 0) is the middle of a
shape or of the viewport, +x right, +y down. Viewport pixel (0, 0) is top-left;
`Compositor.viewport_to_root_local` converts.

## Core nouns

| Learner says | imgcomp type / API | What they should notice |
|--------------|--------------------|-------------------------|
| canvas / screen | `NaiveCompositor(width, height)` + `Surface` | Fixed pixel size; origin in the *center* for drawing math |
| picture / frame | result of `compositor.render(scene)` | One full paint of the scene list |
| saved picture | `compositor.render_png(scene, path)` or `surface.write_png` | PNG they can keep |
| live window | `LivePreview` (`imgcomp.live`) | Same picture, mouse goes back into the scene |
| scene / stack | `Scene` = one `Shape` or a list of shapes | List order: first = back, last = front |
| object / shape | `Shape` | Anything you can ask "what color here?" and "did I hit it?" |
| color | straight `RGBA` tuple `(r, g, b, a)` 0..255 | Alpha = how see-through |
| transparent | `TRANSPARENT` / alpha 0 | Not drawn; pick may still use `hit` |

## Geometry leaves (usually white until painted)

| Learner says | Constructor | Notes |
|--------------|-------------|-------|
| circle / disk | `Circle(radius)` | Centered at local origin |
| rectangle | `Rectangle(half_width, half_height)` | Half-sizes, not full width/height |
| oval / ellipse | `Oval(radius_x, radius_y)` | Axis-aligned until rotated |
| whole background | `Infinite()` | Always hits; paint with `Color` for a backdrop |
| photo / stamp | `ImageObject.load(path)` or `from_rgba_rows` | Bitmap leaf; not an SDF |

SDF leaves (`Circle`, `Rectangle`, `Oval`, and compounds below) sample as white
inside until wrapped in `Color` / `ColorMod`.

## Putting paint on geometry

| Learner says | API | Notes |
|--------------|-----|-------|
| paint it red | `Color(shape, (255, 0, 0, 255))` or `shape.color(...)` | Solid fill wherever child hits |
| fade / tint | `ColorMod(..., a_mul=0.5)` or `shape.color_mod(...)` | Multiplies channels |

## Moves (wrappers -- parent space)

These wrap a child and remaps coordinates. Prefer fluent methods on `Shape`.

| Learner says | API | Notes |
|--------------|-----|-------|
| move it | `Translate(child, tx, ty)` / `.translate(tx, ty)` | Child center goes to (tx, ty) in parent |
| turn it | `Rotate(child, degrees)` / `.rotate(degrees)` | About local origin; +y down |
| stretch it | `Stretch(child, sx, sy)` / `.stretch(sx, sy)` | Non-uniform scale; sx/sy != 0 |

## SDF compounds (geometry algebra)

Only valid on `SDFShape` operands (not arbitrary painted wrappers), except
`Union`, which also accepts painted scene objects and is resolved by `probe`.

| Learner says | API | Notes |
|--------------|-----|-------|
| glue together | `Union(a, b, ...)` / `.union(...)` | Overlap is fine; paint order inside union is back-to-front among members |
| keep overlap | `Intersect(a, b)` / `.intersect(b)` | Both must be SDF geometry |
| cut out | `Subtract(a, b)` / `.subtract(b)` | Cookie-cutter; SDF only |
| puff up | `Fatten(shape, amount)` / `.fatten(amount)` | Grow boundary outward (pixels) |
| shrink | `Thin(shape, amount)` / `.thin(amount)` | Move boundary inward |
| spin the *clay* | `RotateShape` / `.rotate_shape(degrees)` | Field-space rotate (before paint wrappers) |
| stretch the *clay* | `StretchShape` / `.stretch_shape(sx, sy)` | Field-space scale |

Teaching tip: wrappers (`Rotate`) vs shape ops (`rotate_shape`) are easy to
confuse. Early lessons use wrappers only; introduce field ops when boolean
geometry needs a turned rectangle.

## Interaction

| Learner says | API | Notes |
|--------------|-----|-------|
| what did I click? | `compositor.pick(scene, vx, vy)` -> `PickResult` | Topmost hit; local coords on the leaf |
| click / drag / scroll | `dispatch_event(scene, kind, vx, vy, ...)` | Routes to `on_touch` / `on_drag` / `on_scroll` |
| custom handle | subclass `Shape` (or `Circle`, ...) and override `on_*` | See `tests/test_end.py` `MarkupHandle` |

Events use *viewport* pixels in; the object sees *local* center-based coords.

## Frame / time (not a type yet -- REPL concern)

imgcomp has no built-in clock. For animation lessons the REPL (or teacher code)
must own:

| Learner says | Suggested binding | Notes |
|--------------|-------------------|-------|
| frame / tick | callback each refresh | `LivePreview.refresh` is the natural hook |
| time | float seconds or frame index | Passed into scene builders, not into `Shape` itself today |

Caching for ~30fps (dirty layers / unchanged backdrops) is a compositor/REPL
performance concern; learners only need "when I drag, it keeps up."

## Minimal mental model (day one)

1. A *scene* is a stack of *objects*.
2. An object is geometry, optionally *painted* and *moved*.
3. The *canvas* asks every object, pixel by pixel (for now), what color shows.
4. A *click* asks the stack top-down who got hit.

Everything else (unions, fatten, image stamps, live window) is a power-up on
that model.
