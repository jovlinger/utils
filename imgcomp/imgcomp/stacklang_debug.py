"""Debug counters for stacklang <-> Python boundary crossings."""

from __future__ import annotations

import os
import sys
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_ENABLED = os.environ.get("IMGCOMP_STACKLANG_DEBUG", "").lower() in (
    "1",
    "true",
    "yes",
    "on",
)
_SAMPLE_LIMIT = 40
_DEFAULT_LOG_PATH = Path("demo-output/stacklang_debug.log")

_flush_thread: threading.Thread | None = None


@dataclass
class _State:
    counts: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    samples: list[str] = field(default_factory=list)
    preamble: list[str] = field(default_factory=list)

    def reset(self) -> None:
        self.counts.clear()
        self.samples.clear()
        self.preamble.clear()


_state = _State()
_log_path: Path | None = None


def enabled() -> bool:
    return _ENABLED


def set_enabled(on: bool) -> None:
    global _ENABLED
    _ENABLED = on


def configure_logging(log_path: Path | str | None = None) -> Path:
    """Select the buffered debug log file (written on flush)."""
    global _log_path
    if log_path is None:
        env_path = os.environ.get("IMGCOMP_STACKLANG_DEBUG_LOG")
        _log_path = Path(env_path) if env_path else _DEFAULT_LOG_PATH
    else:
        _log_path = Path(log_path)
    return _log_path


def reset() -> None:
    _state.reset()


def note(line: str) -> None:
    """Record a one-off preamble line (scene setup, programs, etc.)."""
    if not _ENABLED:
        return
    _state.preamble.append(line)


def log_py_to_c(site: str, **fields: Any) -> None:
    """Python is calling into the stacklang VM (C)."""
    if not _ENABLED:
        return
    _state.counts[f"py_to_c:{site}"] += 1
    _maybe_sample("py_to_c", site, fields)


def log_c_to_py(site: str, **fields: Any) -> None:
    """Stacklang VM (C) is calling back into Python."""
    if not _ENABLED:
        return
    _state.counts[f"c_to_py:{site}"] += 1
    _maybe_sample("c_to_py", site, fields)


def _maybe_sample(direction: str, site: str, fields: dict[str, Any]) -> None:
    if len(_state.samples) >= _SAMPLE_LIMIT:
        return
    msg = f"{direction} {site}"
    if fields:
        parts: list[str] = []
        for key, value in fields.items():
            if key == "shape" and value is not None:
                parts.append(f"shape={type(value).__name__}")
            else:
                parts.append(f"{key}={value!r}")
        msg = f"{msg} {' '.join(parts)}"
    _state.samples.append(msg)


def _report_lines() -> list[str]:
    lines = list(_state.preamble)
    lines.append("stacklang debug summary:")
    for key in sorted(_state.counts):
        lines.append(f"  {key}: {_state.counts[key]}")
    if _state.samples:
        lines.append("stacklang debug samples:")
        for line in _state.samples:
            lines.append(f"  {line}")
    return lines


def flush(log_path: Path | str | None = None, *, wait: bool = False) -> Path | None:
    """Write the buffered report to disk on a background thread."""
    global _flush_thread
    if not _ENABLED:
        return None
    target = Path(log_path) if log_path is not None else _log_path
    if target is None:
        return None
    body = "\n".join(_report_lines()) + "\n"

    def _write() -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="ascii", errors="backslashreplace")

    _flush_thread = threading.Thread(
        target=_write,
        name="stacklang-debug-flush",
        daemon=False,
    )
    _flush_thread.start()
    if wait:
        _flush_thread.join()
    return target


def print_summary(*, log_path: Path | str | None = None, wait: bool = True) -> Path | None:
    """Print summary to stderr and flush the buffered log file."""
    if not _state.counts and not _state.samples and not _state.preamble:
        print("stacklang debug: no boundary crossings recorded", file=sys.stderr)
        return flush(log_path, wait=wait)
    for line in _report_lines():
        print(line, file=sys.stderr)
    written = flush(log_path, wait=wait)
    if written is not None:
        print(f"stacklang debug log: {written.resolve()}", file=sys.stderr)
    return written
