# imgcomp: naive per-pixel compositor

This branch is the **baseline rendering strategy**: pure Python, no Cython,
no PIC specialization, no quad tile cache.

## Algorithm

```
Scene z-list
    |
    v
for each pixel (x, y):
    for each layer (front to back):
        color = shape.color_at(local_x, local_y)
        accum = src_over(color, accum)
    write accum to surface
```

Every pixel walks the full `Shape` tree via `color_at`, `Union`, wrappers, and
SDF `distance` in Python.

## C-FFI boundaries

None. No extensions are built on this branch.

## REPL layer cache

`ReplSession.render(use_cache=True)` uses `LayerCache`: per top-level scene
entry rasterized once under `content_key`, then composited. That is a separate
Python-level cache, not quad/PIC.

## Related branches

| Branch | Strategy |
|--------|----------|
| `imgcomp-naive-cache-zlist-per-cell` | Flat grid per-cell z-list slices |
| `imgcomp-recursive-zlist-color-at` | Z-list recursion inside ``color_at`` |
| `imgcomp-layer-paint-farthest-first` | Each z-list item paints full viewport |
| `imgcomp-pic-paint-quad-off` | PIC typed paint, no quad |
| `imgcomp-pic-paint-quad-on` | PIC + quad tile cache |
| `imgcomp-naive-cython-leaf` | This spine + Cython SDF distance patched in ``__init__`` |
