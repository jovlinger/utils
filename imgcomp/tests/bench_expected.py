"""Reference correctness values shared by render and stack benchmarks."""

from __future__ import annotations

# Opaque (alpha 255) pixel counts for 192x192 gallery scenes and simpletest 512.
# Canonical values match stacklang / C / directstack compositing.
EXPECTED_RENDER_WHITE_PX: dict[str, int] = {
    "simpletest": 126_152,
    "carpet": 36_864,
    "phyllotaxis": 36_864,
    "rings": 7_488,
    "spirograph": 7_488,
}

# Per-render-path overrides when a branch's sole path differs (e.g. python Infinite bg).
PATH_RENDER_WHITE_PX_OVERRIDES: dict[str, dict[str, int]] = {
    "python": {
        "rings": 36_864,
        "spirograph": 36_864,
    },
}


def expected_render_white_px(scene: str, *, path_key: str) -> int | None:
    """Return expected opaque-pixel count for a scene and bench path key."""
    override = PATH_RENDER_WHITE_PX_OVERRIDES.get(path_key, {}).get(scene)
    if override is not None:
        return override
    return EXPECTED_RENDER_WHITE_PX.get(scene)

# Stack workload results (same parameters as tests/bench_stack_run.py).
EXPECTED_STACK_VALUES: dict[str, int | float] = {
    "ack": 61,
    "float_step_sum": 4_512_504.749954834,
    "int_step_sum": 451_250_475_000,
    "mandel_sum": 14_809,
}
