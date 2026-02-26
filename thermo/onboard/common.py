"""
Standard functions used everywhere. Logging configured for app and twoway.
"""

from __future__ import annotations

import logging
import os
import sys
import time

# possibly the least informative name ever
ENVVAR = "ENV"


def is_test_env() -> bool:
    """Are we running in a test environment?"""
    return os.environ.get(ENVVAR) in ["TEST", "DOCKERTEST"]


# ---------------------------------------------------------------------------
# Logging: single-line format 2025-02-22T12:34:56.123 component: msg
# ---------------------------------------------------------------------------


def _env_int(name: str, default: int) -> int:
    v = os.environ.get(name)
    return int(v) if v else default


LOG_PATH = os.environ.get("LOG_PATH")
LOG_MAX_LINES = _env_int("LOG_MAX_LINES", 500)
LOG_MAX_BYTES = _env_int("LOG_MAX_BYTES", 0)


class MillisecondFormatter(logging.Formatter):
    """Single-line format: 2025-02-22T12:34:56.123 component: msg"""

    def formatTime(self, record, datefmt=None):
        ct = self.converter(record.created)
        if datefmt:
            s = time.strftime(datefmt, ct)
        else:
            s = time.strftime("%Y-%m-%dT%H:%M:%S", ct)
        msecs = int((record.created % 1) * 1000)
        return f"{s}.{msecs:03d}"


def _prune(path: str) -> None:
    """Keep last LOG_MAX_LINES (or fit in LOG_MAX_BYTES)."""
    if not os.path.exists(path):
        return
    try:
        with open(path) as f:
            lines = f.readlines()
    except OSError:
        return
    if LOG_MAX_BYTES > 0:
        total = 0
        keep: list[str] = []
        for line in reversed(lines):
            keep.append(line)
            total += len(line.encode())
            if total >= LOG_MAX_BYTES:
                break
        lines = list(reversed(keep))
    elif len(lines) >= LOG_MAX_LINES:
        lines = lines[-(LOG_MAX_LINES - 1) :]
    if len(lines) < 1:
        return
    try:
        with open(path, "w") as f:
            f.writelines(lines)
    except OSError:
        pass


class PrunedFileHandler(logging.Handler):
    """Append to file and prune before each emit."""

    def emit(self, record):
        try:
            if LOG_PATH:
                _prune(LOG_PATH)
                msg = self.format(record)
                with open(LOG_PATH, "a") as f:
                    f.write(msg + "\n")
        except OSError:
            self.handleError(record)


def configure_logging() -> None:
    """Configure onboard logger: stderr + optional pruned file. Same for app and twoway."""
    root = logging.getLogger("onboard")
    root.setLevel(logging.INFO)
    root.handlers.clear()

    fmt = "%(asctime)s %(message)s"
    formatter = MillisecondFormatter(fmt)

    h = logging.StreamHandler(sys.stderr)
    h.setFormatter(formatter)
    root.addHandler(h)

    if LOG_PATH:
        h = PrunedFileHandler()
        h.setFormatter(formatter)
        root.addHandler(h)


configure_logging()


def log(component: str, msg: str, **kwargs) -> None:
    """Single-line log. component is 'app' or 'twoway'."""
    extra = " " + " ".join(f"{k}={v!r}" for k, v in kwargs.items()) if kwargs else ""
    logger = logging.getLogger("onboard")
    logger.info("%s: %s%s", component, msg, extra)
