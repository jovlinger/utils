"""
Standard logging setup for the DMZ Flask app.

Call ``configure_logging("dmz")`` once at startup. Output goes to stdout for
``run-with-stdout-logged.py`` to capture and rotate.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Optional

# Below DEBUG (stdlib has no TRACE); enable with LOG_LEVEL=TRACE.
# trace is monkey-patched in.
TRACE = 5
logging.addLevelName(TRACE, "TRACE")

LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
_VALID_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "TRACE": TRACE,
    "NOTSET": logging.NOTSET,
}

_configured = False


def _logger_trace(
    self: logging.Logger,
    msg: object,
    *args: object,
    exc_info: Any = None,
    stack_info: bool = False,
    stacklevel: int = 1,
    extra: Any = None,
) -> None:
    if self.isEnabledFor(TRACE):
        self._log(
            TRACE,
            msg,
            args,
            exc_info=exc_info,
            stack_info=stack_info,
            stacklevel=stacklevel,
            extra=extra,
        )


if not getattr(logging.Logger, "trace", None):
    logging.Logger.trace = _logger_trace  # type: ignore[method-assign]


class _UtcWallClockFormatter(logging.Formatter):
    """UTC timestamps from ``time.time()`` when the line is formatted (not monotonic)."""

    def formatTime(
        self, record: logging.LogRecord, datefmt: Optional[str] = None
    ) -> str:
        del record
        wall = time.time()
        ct = time.gmtime(wall)
        fmt = datefmt or "%Y-%m-%dT%H:%M:%S"
        return f"{time.strftime(fmt, ct)}.{int((wall % 1.0) * 1000):03d}"


class _ServiceFilter(logging.Filter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self._service  # type: ignore[attr-defined]
        return True


def format_kv(**kwargs: Any) -> str:
    """Append `` key=value`` pairs for structured fields in log messages."""
    if not kwargs:
        return ""
    return " " + " ".join(f"{k}={v!r}" for k, v in kwargs.items())


def configure_logging(service: str) -> None:
    """Configure root logger: UTC timestamps, service tag, module:lineno, stdout."""
    global _configured
    if _configured:
        return
    level = _VALID_LOG_LEVELS.get(LOG_LEVEL, logging.DEBUG)
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = _UtcWallClockFormatter(
        "%(asctime)sZ %(levelname)s %(service)s %(name)s:%(lineno)d %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(_ServiceFilter(service))
    root.addHandler(handler)
    # Werkzeug request lines must go through root stdout (run-with-stdout-logged → dmz.log).
    werkzeug_log = logging.getLogger("werkzeug")
    werkzeug_log.handlers.clear()
    werkzeug_log.propagate = True
    _configured = True


def get_log_level() -> str:
    """Return current root logger level name."""
    return logging.getLevelName(logging.getLogger().getEffectiveLevel())


def set_log_level(level_name: str) -> Optional[str]:
    """Set root logger level from name. Returns normalized level or None."""
    if not level_name:
        return None
    normalized = level_name.upper().strip()
    level = _VALID_LOG_LEVELS.get(normalized)
    if level is None:
        return None
    logging.getLogger().setLevel(level)
    return normalized
