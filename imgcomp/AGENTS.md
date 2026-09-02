# imgcomp master

## Render benchmarks

``tests/bench_render.py`` on master times **python only** (quadtree leaf-cell
batch via ``render_quadtree_python``). Fast native paths live on sibling
branches: ``imgcomp_stacklang``, ``imgcomp_directstack``, ``imgcomp_c``.

Stacklang render code remains for unit tests and ``render_stacklang`` helpers,
but is not part of the master bench registry.

### min_size hillclimb

Re-tune after render-path changes with ``tests/bench_render.py --tune-min-size``.
Cached per-path values live in ``imgcomp/render_tune.py``.
