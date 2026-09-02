"""Bench timing policy: global warming is build-only, not in self-reported times."""

from __future__ import annotations

from pathlib import Path

_TESTS = Path(__file__).resolve().parent


def test_bench_render_does_not_invoke_global_warming() -> None:
    source = (_TESTS / "bench_render.py").read_text(encoding="utf-8")
    assert "warm_render_benchmarks()" not in source
    assert "global_warming" not in source


def test_bench_stack_run_does_not_invoke_global_warming() -> None:
    stack_path = _TESTS / "bench_stack_run.py"
    if not stack_path.is_file():
        return
    source = stack_path.read_text(encoding="utf-8")
    assert "warm_stack_benchmarks()" not in source
    assert "global_warming" not in source


def test_makefile_bench_depends_on_global_warming_stamp() -> None:
    makefile = (_TESTS.parent / "Makefile").read_text(encoding="utf-8")
    assert "GLOBAL_WARMING_STAMP" in makefile
    assert "bench-render: $(GLOBAL_WARMING_STAMP)" in makefile
    assert "build-ext: $(BUILD_STAMP) $(GLOBAL_WARMING_STAMP)" in makefile
