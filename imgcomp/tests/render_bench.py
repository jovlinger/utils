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

from imgcomp.stacklang_debug import configure_logging, enabled, note, print_summary, reset, set_enabled
from imgcomp.stacklang_render import prepare_scene
from imgcomp.scene import Scene
from imgcomp.stacklang_render import render
from imgcomp.surface import Surface
from tests.fractal_scenes import fractal_gallery_scene
from tests.simpletest import (
    VIEWPORT,
    render_c,
    render_python,
    render_stacklang,
    simpletest_scene,
    surface_white_count,
)

RenderFn = Callable[[Scene, int, int], Surface]

GALLERY_SIZE = 192
GALLERY_PROFILE = "fast"
DEFAULT_OUTPUT = Path("demo-output")
TIMINGS_FILE = "timings.json"
HISTORY_LIMIT = 10


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
    png_path_key: str = "stacklang"


@dataclass
class PathResult:
    key: str
    seconds: float
    surface: Surface


@dataclass
class BenchmarkResult:
    name: str
    width: int
    height: int
    repeat: int
    paths: dict[str, PathResult] = field(default_factory=dict)
    png_path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _gallery_scene(kind: str) -> Scene:
    return fractal_gallery_scene(kind, size=GALLERY_SIZE, profile=GALLERY_PROFILE)


def _python_path() -> RenderPath:
    return RenderPath("python", render_python)


def _stacklang_path() -> RenderPath:
    return RenderPath("stacklang", render_stacklang)


def _c_path() -> RenderPath:
    return RenderPath("c", render_c)


BENCHMARKS: dict[str, Benchmark] = {
    "simpletest": Benchmark(
        name="simpletest",
        width=VIEWPORT,
        height=VIEWPORT,
        scene=simpletest_scene,
        paths=(_python_path(), _stacklang_path(), _c_path()),
        png_path_key="stacklang",
    ),
    "carpet": Benchmark(
        name="carpet",
        width=GALLERY_SIZE,
        height=GALLERY_SIZE,
        scene=lambda: _gallery_scene("carpet"),
        paths=(_python_path(), _stacklang_path()),
    ),
    "phyllotaxis": Benchmark(
        name="phyllotaxis",
        width=GALLERY_SIZE,
        height=GALLERY_SIZE,
        scene=lambda: _gallery_scene("phyllotaxis"),
        paths=(_python_path(), _stacklang_path()),
    ),
    "rings": Benchmark(
        name="rings",
        width=GALLERY_SIZE,
        height=GALLERY_SIZE,
        scene=lambda: _gallery_scene("rings"),
        paths=(_python_path(), _stacklang_path()),
    ),
    "spirograph": Benchmark(
        name="spirograph",
        width=GALLERY_SIZE,
        height=GALLERY_SIZE,
        scene=lambda: _gallery_scene("spirograph"),
        paths=(_python_path(), _stacklang_path()),
    ),
}

ALL_BENCHMARK_NAMES: tuple[str, ...] = tuple(BENCHMARKS.keys())


def time_render(
    render_fn: RenderFn,
    scene: Scene,
    width: int,
    height: int,
    *,
    repeat: int,
    warmup: int,
) -> tuple[Surface, float]:
    """Return the last surface and total seconds for ``repeat`` timed renders."""
    if repeat < 1:
        raise ValueError("repeat must be >= 1")
    if warmup < 0:
        raise ValueError("warmup must be >= 0")

    for _ in range(warmup):
        render_fn(scene, width, height)

    start = time.perf_counter()
    surface: Surface | None = None
    for _ in range(repeat):
        surface = render_fn(scene, width, height)
    elapsed = time.perf_counter() - start
    if surface is None:
        raise RuntimeError("render produced no surface")
    return surface, elapsed


def _describe_stacklang(scene: Scene) -> None:
    if not enabled():
        return
    note("stacklang programs:")
    for layer in prepare_scene(scene):
        shape_name = type(layer.shape).__name__
        note(f"  layer {layer.index} {shape_name}: {layer.color_stacklang!r}")


def run_benchmark(
    spec: Benchmark,
    *,
    output_dir: Path,
    repeat: int = 1,
    warmup: int = 1,
) -> BenchmarkResult:
    """Time each path, then write the showcase PNG outside the timer."""
    scene = spec.scene()
    result = BenchmarkResult(
        name=spec.name,
        width=spec.width,
        height=spec.height,
        repeat=repeat,
    )

    for path in spec.paths:
        if enabled() and path.key == "stacklang":
            reset()
            note(f"benchmark {spec.name} {spec.width}x{spec.height}")
            _describe_stacklang(scene)
        surface, seconds = time_render(
            path.render,
            scene,
            spec.width,
            spec.height,
            repeat=repeat,
            warmup=warmup,
        )
        result.paths[path.key] = PathResult(key=path.key, seconds=seconds, surface=surface)

    if spec.name == "simpletest":
        py_surface = result.paths["python"].surface
        result.extra["white_px"] = {
            key: surface_white_count(path.surface)
            for key, path in result.paths.items()
        }
        result.extra["white_px_match"] = len({surface_white_count(p.surface) for p in result.paths.values()}) == 1

    showcase = result.paths[spec.png_path_key].surface
    output_dir.mkdir(parents=True, exist_ok=True)
    png_path = output_dir / f"{spec.name}.png"
    showcase.write_png(png_path)
    result.png_path = png_path.resolve()
    return result


def run_selected(
    names: Sequence[str],
    *,
    output_dir: Path = DEFAULT_OUTPUT,
    repeat: int = 1,
    warmup: int = 1,
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
        )
    return results


def _load_timings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"history": []}
    return json.loads(path.read_text())


def _save_timings(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n")


def _result_to_record(result: BenchmarkResult) -> dict[str, Any]:
    record: dict[str, Any] = {
        "width": result.width,
        "height": result.height,
        "repeat": result.repeat,
        "png": str(result.png_path) if result.png_path else None,
        "paths": {key: path.seconds for key, path in result.paths.items()},
    }
    if result.extra:
        record["extra"] = result.extra
    return record


def _print_result(result: BenchmarkResult, *, previous: dict[str, Any] | None) -> None:
    parts = [f"{result.name}:"]
    for key, path in result.paths.items():
        line = f"{key}_s={path.seconds:.6f}"
        if previous and key in previous.get("paths", {}):
            old = float(previous["paths"][key])
            if old > 0.0:
                delta = (path.seconds - old) / old * 100.0
                line += f" ({delta:+.1f}% vs last)"
        parts.append(line)
    if "white_px" in result.extra:
        parts.append(f"white_px={result.extra['white_px']}")
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
        "--debug-stacklang",
        action="store_true",
        help="log stacklang <-> Python boundary crossings to stderr",
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

    if args.debug_stacklang:
        set_enabled(True)
        log_path = configure_logging(args.output / "stacklang_debug.log")
        reset()
        note(f"debug log path: {log_path}")

    timings_path = args.output / TIMINGS_FILE
    previous_payload = _load_timings(timings_path)

    try:
        results = run_selected(
            args.names,
            output_dir=args.output,
            repeat=args.repeat,
            warmup=args.warmup,
        )
    except ValueError as exc:
        parser.error(str(exc))
        return 2

    print_results(results, previous_payload=previous_payload)
    record_run(results, output_dir=args.output, previous_payload=previous_payload)
    if args.debug_stacklang:
        print_summary(log_path=args.output / "stacklang_debug.log", wait=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
