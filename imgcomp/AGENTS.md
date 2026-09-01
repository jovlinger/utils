# imgcomp master

## Render driver

Stacklang fractal render uses ``render_quadtree()`` in ``_stacklang_render_c.pyx``:
walk quadtree leaves and paint each cell's pixels in batch (no per-pixel
``z_list_at_point`` in the hot loop). Python reference uses
``render_quadtree_python`` in ``naive.py`` with the same leaf-cell batch shape.

### min_size hillclimb

Re-tune after render-path changes with ``tests/bench_render.py --tune-min-size``.
Cached per-path values live in ``imgcomp/render_tune.py`` (RMS frame ms; not
apples-to-apples across paths).

### Vectorization (per-cell inner loop)

``_paint_leaf_cell`` still calls ``invoke_member_rgba`` once per pixel. Vectorizing
the inner loop needs either SIMD over gx/gy tiles or a closed member-composite
kernel decoupled from open-ended stacklang dispatch. Not implemented on master.
