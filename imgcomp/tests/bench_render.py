#!/usr/bin/env venv-run
# fmt: off
"""Image render benchmarks: time render paths, write PNGs outside the timer."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import argparse
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from imgcomp.scene import Scene
from imgcomp.surface import Surface
from tests.fractal_scenes import fractal_gallery_scene
from tests.bench_expected import expected_render_white_px
from tests.simpletest import (
    VIEWPORT,
    render_python,
    simpletest_scene,
    surface_white_count,
)

RenderFn = Callable[..., Surface]

GALLERY_SIZE = 192
GALLERY_PROFILE = "fast"
DEFAULT_OUTPUT = Path("demo-output")
TIMINGS_FILE = "timings.json"
HISTORY_LIMIT = 10
BENCH_PATH_KEY = "python"


@dataclass(frozen=True)
class RenderPath:
    """One render implementation to benchmark."""

    key: str
    render: RenderFn


@dataclass(frozen=True)
class Benchmark:
    """Scene preset with one or more render paths."""

    name: str
    width: int
    height: int
    scene: Callable[[], Scene]
    paths: tuple[RenderPath, ...]
    png_path_key: str = "python"


@dataclass
class PathResult:
    key: str
    seconds: float
    iteration_seconds: list[float]
    surface: Surface


@dataclass
class BenchmarkResult:
    name: str
    width: int
    height: int
    repeat: int
    paths: dict[str, PathResult] = field(default_factory=dict)
    total_seconds: float = 0.0
    png_path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _gallery_scene(kind: str) -> Scene:
    return fractal_gallery_scene(kind, size=GALLERY_SIZE, profile=GALLERY_PROFILE)


def bench_render_path() -> RenderPath:
    return RenderPath(BENCH_PATH_KEY, render_python)


def _bench_paths() -> tuple[RenderPath, ...]:
    return (bench_render_path(),)


BENCHMARKS: dict[str, Benchmark] = {
    "simpletest": Benchmark(
        name="simpletest",
        width=VIEWPORT,
        height=VIEWPORT,
        scene=simpletest_scene,
        paths=_bench_paths(),
        png_path_key=BENCH_PATH_KEY,
    ),
    "carpet": Benchmark(
        name="carpet",
        width=GALLERY_SIZE,
        height=GALLERY_SIZE,
        scene=lambda: _gallery_scene("carpet"),
        paths=_bench_paths(),
    ),
    "phyllotaxis": Benchmark(
        name="phyllotaxis",
        width=GALLERY_SIZE,
        height=GALLERY_SIZE,
        scene=lambda: _gallery_scene("phyllotaxis"),
        paths=_bench_paths(),
    ),
    "rings": Benchmark(
        name="rings",
        width=GALLERY_SIZE,
        height=GALLERY_SIZE,
        scene=lambda: _gallery_scene("rings"),
        paths=_bench_paths(),
    ),
    "spirograph": Benchmark(
        name="spirograph",
        width=GALLERY_SIZE,
        height=GALLERY_SIZE,
        scene=lambda: _gallery_scene("spirograph"),
        paths=_bench_paths(),
        png_path_key=BENCH_PATH_KEY,
    ),
}

ALL_BENCHMARK_NAMES: tuple[str, ...] = tuple(BENCHMARKS.keys())


def time_render(
    render_fn: RenderFn,
    scene_fn: Callable[[], Scene],
    width: int,
    height: int,
    *,
    repeat: int,
    warmup: int,
    min_size: float = 16.0,
) -> tuple[Surface, float, float, list[float]]:
    """Return the last surface, timed wall seconds, timed self-report total, iter times."""
    if repeat < 1:
        raise ValueError("repeat must be >= 1")
    if warmup < 0:
        raise ValueError("warmup must be >= 0")

    for _ in range(warmup):
        render_fn(scene_fn(), width, height, min_size=min_size)

    timed_wall_start = time.perf_counter()
    iteration_seconds: list[float] = []
    surface: Surface | None = None
    for _ in range(repeat):
        iter_start = time.perf_counter()
        surface = render_fn(scene_fn(), width, height, min_size=min_size)
        iteration_seconds.append(time.perf_counter() - iter_start)
    timed_wall_s = time.perf_counter() - timed_wall_start
    if surface is None:
        raise RuntimeError("render produced no surface")
    return surface, timed_wall_s, sum(iteration_seconds), iteration_seconds


def run_benchmark(
    spec: Benchmark,
    *,
    output_dir: Path,
    repeat: int = 1,
    warmup: int = 1,
    tune_min_size: bool = False,
) -> BenchmarkResult:
    """Time each path, then write the showcase PNG outside the timer."""
    from imgcomp.render_tune import hillclimb_min_size, tuned_min_size

    bench_start = time.perf_counter()
    result = BenchmarkResult(
        name=spec.name,
        width=spec.width,
        height=spec.height,
        repeat=repeat,
    )

    for path in spec.paths:
        if tune_min_size:
            hillclimb_min_size(
                path.key,
                path.render,
                spec.scene(),
                spec.width,
                spec.height,
                repeat=max(1, repeat - 1),
                warmup=warmup,
            )
        min_size = tuned_min_size(path.key)
        surface, timed_wall_s, seconds, iteration_seconds = time_render(
            path.render,
            spec.scene,
            spec.width,
            spec.height,
            repeat=repeat,
            warmup=warmup,
            min_size=min_size,
        )
        result.paths[path.key] = PathResult(
            key=path.key,
            seconds=seconds,
            iteration_seconds=iteration_seconds,
            surface=surface,
        )
        result.extra.setdefault("timing_audit", {})[path.key] = {
            "timed_wall_s": timed_wall_s,
            "timed_self_s": seconds,
            "wall_minus_self_s": timed_wall_s - seconds,
        }

    expected_white = expected_render_white_px(spec.name, path_key=BENCH_PATH_KEY)
    result.extra["white_px"] = {
        key: surface_white_count(path.surface)
        for key, path in result.paths.items()
    }
    if expected_white is not None:
        bench_white = result.extra["white_px"][BENCH_PATH_KEY]
        result.extra["white_px_expected"] = expected_white
        result.extra["white_px_ok"] = bench_white == expected_white
        if not result.extra["white_px_ok"]:
            raise RuntimeError(
                f"{spec.name}: {BENCH_PATH_KEY} white_px={bench_white} "
                f"expected {expected_white}"
            )

    showcase = result.paths[spec.png_path_key].surface
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / f"{spec.name}.png"
    showcase.write_png(png_path)
    result.png_path = png_path.resolve()
    result.total_seconds = time.perf_counter() - bench_start
    return result


def run_selected(
    names: Sequence[str],
    *,
    output_dir: Path = DEFAULT_OUTPUT,
    repeat: int = 1,
    warmup: int = 1,
    tune_min_size: bool = False,
) -> dict[str, BenchmarkResult]:
    """Run named benchmarks; default registry order when ``names`` is empty."""
    selected = list(names) if names else list(ALL_BENCHMARK_NAMES)
    unknown = [name for name in selected if name not in BENCHMARKS]
    if unknown:
        raise ValueError(f"unknown benchmark(s): {', '.join(unknown)}")

    results: dict[str, BenchmarkResult] = {}
    for name in selected:
        results[name] = run_benchmark(
            BENCHMARKS[name],
            output_dir=output_dir,
            repeat=repeat,
            warmup=warmup,
            tune_min_size=tune_min_size,
        )
    return results


def _load_timings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"history": []}
    return json.loads(path.read_text())


def _save_timings(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _path_total_from_record(path_data: Any) -> float | None:
    """Read a path total from current or legacy ``timings.json`` records."""
    if isinstance(path_data, (int, float)):
        return float(path_data)
    if isinstance(path_data, dict):
        total = path_data.get("total_s")
        if total is not None:
            return float(total)
    return None


def _format_iter_seconds(key: str, iteration_seconds: Sequence[float]) -> str:
    inner = ",".join(f"{seconds:.6f}" for seconds in iteration_seconds)
    return f"{key}_iter_s=[{inner}]"


def _result_to_record(result: BenchmarkResult) -> dict[str, Any]:
    record: dict[str, Any] = {
        "width": result.width,
        "height": result.height,
        "repeat": result.repeat,
        "total_s": result.total_seconds,
        "png": str(result.png_path) if result.png_path else None,
        "paths": {
            key: {
                "total_s": path.seconds,
                "iter_s": list(path.iteration_seconds),
            }
            for key, path in result.paths.items()
        },
    }
    if result.extra:
        record["extra"] = result.extra
    return record


def _print_result(result: BenchmarkResult, *, previous: dict[str, Any] | None) -> None:
    parts = [f"{result.name}:"]
    for key, path in result.paths.items():
        line = (
            f"{_format_iter_seconds(key, path.iteration_seconds)} "
            f"{key}_total_s={path.seconds:.6f}"
        )
        if previous is not None:
            old = _path_total_from_record(previous.get("paths", {}).get(key))
            if old is not None and old > 0.0:
                delta = (path.seconds - old) / old * 100.0
                line += f" ({delta:+.1f}% vs last)"
        parts.append(line)
    parts.append(f"test_total_s={result.total_seconds:.6f}")
    if previous is not None:
        old_total = previous.get("total_s")
        if old_total is not None and float(old_total) > 0.0:
            delta = (result.total_seconds - float(old_total)) / float(old_total) * 100.0
            parts[-1] += f" ({delta:+.1f}% vs last)"
    if "white_px" in result.extra:
        parts.append(f"white_px={result.extra['white_px']}")
    audit = result.extra.get("timing_audit", {}).get(BENCH_PATH_KEY)
    if audit is not None:
        parts.append(
            "audit "
            f"wall={audit['timed_wall_s']:.6f}s "
            f"self={audit['timed_self_s']:.6f}s "
            f"delta={audit['wall_minus_self_s']:.6f}s"
        )
    if result.png_path is not None:
        parts.append(f"png={result.png_path}")
    print("  ".join(parts))


def record_run(
    results: dict[str, BenchmarkResult],
    *,
    output_dir: Path,
    previous_payload: dict[str, Any],
) -> dict[str, Any]:
    """Append this run to ``demo-output/timings.json`` and return the new payload."""
    run_at = datetime.now(timezone.utc).isoformat()
    current = {
        "run_at": run_at,
        "benchmarks": {name: _result_to_record(result) for name, result in results.items()},
    }
    history = list(previous_payload.get("history", []))
    if previous_payload.get("current"):
        history.append(previous_payload["current"])
    history = history[-HISTORY_LIMIT:]
    payload = {"current": current, "history": history}
    _save_timings(output_dir / TIMINGS_FILE, payload)
    return payload


def print_results(
    results: dict[str, BenchmarkResult],
    *,
    previous_payload: dict[str, Any] | None = None,
) -> None:
    previous_benchmarks: dict[str, Any] = {}
    if previous_payload and previous_payload.get("current"):
        previous_benchmarks = previous_payload["current"].get("benchmarks", {})
    for name, result in results.items():
        _print_result(result, previous=previous_benchmarks.get(name))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "names",
        nargs="*",
        metavar="NAME",
        help=f"benchmark name(s); default all ({', '.join(ALL_BENCHMARK_NAMES)})",
    )
    parser.add_argument("--list", action="store_true", help="list benchmark names and exit")
    parser.add_argument("--repeat", type=int, default=1, help="timed render repetitions (default 1)")
    parser.add_argument("--warmup", type=int, default=1, help="untimed warmup renders per path (default 1)")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"output directory for PNGs and {TIMINGS_FILE} (default demo-output)",
    )
    parser.add_argument(
        "--tune-min-size",
        action="store_true",
        help="hillclimb quadtree min_size per path before timing (RMS frame ms)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.list:
        for name in ALL_BENCHMARK_NAMES:
            spec = BENCHMARKS[name]
            path_keys = ", ".join(path.key for path in spec.paths)
            print(f"{name}: {spec.width}x{spec.height} paths=[{path_keys}] png={spec.png_path_key}")
        return 0

    if args.repeat < 1:
        parser.error("--repeat must be >= 1")
    if args.warmup < 0:
        parser.error("--warmup must be >= 0")

    from tests.global_warming import warm_render_benchmarks

    warm_render_benchmarks()

    timings_path = args.output / TIMINGS_FILE
    previous_payload = _load_timings(timings_path)

    try:
        results = run_selected(
            args.names,
            output_dir=args.output,
            repeat=args.repeat,
            warmup=args.warmup,
            tune_min_size=args.tune_min_size,
        )
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    print_results(results, previous_payload=previous_payload)
    record_run(results, output_dir=args.output, previous_payload=previous_payload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
