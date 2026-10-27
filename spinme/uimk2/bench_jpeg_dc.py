#!/usr/bin/env python3
"""Host PoC: cost of JPEG -> 360x360 via full decode vs DC-ish (1/8 draft).

DC-only / 1/8: JPEG MCU is 8x8; keeping only the DC coefficient per block
yields one pixel per MCU (1/8 linear). Pillow draft approximates that cheap
path. Then nearest-neighbor integer scale to PANEL (360).

Usage (from this directory or any cwd):
  ../.venv-tools/bin/python bench_jpeg_dc.py [path.jpg ...]
  With no args, uses /tmp/Disintegration-*.jpg if present.

Prints mean us over N reps for each path. Extrapolates a rough ESP32-S3
range using the ~180-200x blit slowdown from BENCH.md (decode is not blit;
treat as order-of-magnitude only).
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path
from typing import Callable, List, Sequence, Tuple

from PIL import Image

PANEL = 360
N = 50
WARM = 8
# Order-of-magnitude from spinme/uimk2/BENCH.md blit ESP/host ratio.
ESP_SLOWDOWN_LO = 180.0
ESP_SLOWDOWN_HI = 200.0


def _paths(argv: Sequence[str]) -> List[Path]:
    if argv:
        return [Path(a) for a in argv]
    found = sorted(Path("/tmp").glob("Disintegration*.jpg"))
    if not found:
        raise SystemExit("no jpg args and no /tmp/Disintegration*.jpg")
    return found


def _time_us(fn: Callable[[], None], n: int = N, warm: int = WARM) -> float:
    for _ in range(warm):
        fn()
    samples: List[float] = []
    for _ in range(n):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1e6)
    return statistics.mean(samples)


def bench_full(path: Path) -> Tuple[float, Tuple[int, int]]:
    data = path.read_bytes()

    def once() -> None:
        im = Image.open(__import__("io").BytesIO(data))
        rgb = im.convert("RGB")
        out = rgb.resize((PANEL, PANEL), Image.Resampling.NEAREST)
        out.load()

    return _time_us(once), Image.open(path).size


def bench_dc_draft(path: Path) -> Tuple[float, Tuple[int, int], Tuple[int, int]]:
    """JPEG draft to ~1/8, then nearest to 360 (integer scale of DC grid)."""
    data = path.read_bytes()

    def once() -> None:
        bio = __import__("io").BytesIO(data)
        im = Image.open(bio)
        w, h = im.size
        # Request ~1/8; decoder may pick a supported draft size.
        im.draft("RGB", (max(1, w // 8), max(1, h // 8)))
        small = im.convert("RGB")
        out = small.resize((PANEL, PANEL), Image.Resampling.NEAREST)
        out.load()

    im0 = Image.open(path)
    w0, h0 = im0.size
    im0.draft("RGB", (max(1, w0 // 8), max(1, h0 // 8)))
    draft_size = im0.convert("RGB").size
    return _time_us(once), (w0, h0), draft_size


def main() -> None:
    paths = _paths(sys.argv[1:])
    print(
        "bench_jpeg_dc PANEL={0} N={1} warm={2} (host Pillow)".format(
            PANEL, N, WARM
        )
    )
    for path in paths:
        if not path.is_file():
            print("skip missing {0}".format(path))
            continue
        nbytes = path.stat().st_size
        full_us, size = bench_full(path)
        dc_us, size2, draft = bench_dc_draft(path)
        assert size == size2
        print(
            "file={0} bytes={1} src={2}x{3} draft~={4}x{5}".format(
                path.name, nbytes, size[0], size[1], draft[0], draft[1]
            )
        )
        print(
            "  full_decode+nn360  mean_us={0:.1f}  esp_est_ms={1:.1f}..{2:.1f}".format(
                full_us,
                full_us * ESP_SLOWDOWN_LO / 1000.0,
                full_us * ESP_SLOWDOWN_HI / 1000.0,
            )
        )
        print(
            "  dc_draft1/8+nn360  mean_us={0:.1f}  esp_est_ms={1:.1f}..{2:.1f}  "
            "vs_full={3:.2f}x".format(
                dc_us,
                dc_us * ESP_SLOWDOWN_LO / 1000.0,
                dc_us * ESP_SLOWDOWN_HI / 1000.0,
                full_us / dc_us if dc_us > 0 else 0.0,
            )
        )
    print(
        "note: esp_est uses blit slowdown ~180-200x; JPEG on S3 (JPEGDEC 1/8) "
        "is often closer to tens of ms for album-art sizes -- verify on device."
    )


if __name__ == "__main__":
    main()
