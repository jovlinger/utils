"""
Standard logging setup for onboard processes (Flask app, twoway, connectivity watchdog).

Each entrypoint calls ``configure_logging("onboard")`` or ``configure_logging("twoway")``
once at startup. Output goes to stdout for ``run-with-stdout-logged.py`` to capture.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from collections import deque
from threading import RLock
from typing import Any, Optional

LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
_VALID_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}

_configured = False
_LOG_BUFFER_DEFAULT_LINES = 200
_log_buffer_lock = RLock()
_log_buffer: deque[str] = deque(
    maxlen=int(
        os.environ.get("ONBOARD_HEALTH_LOG_LINES", str(_LOG_BUFFER_DEFAULT_LINES))
    )
)


class _RollingLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
        except Exception:
            self.handleError(record)
            return
        with _log_buffer_lock:
            _log_buffer.append(msg)


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

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03dZ %(levelname)s %(service)s %(name)s:%(lineno)d %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(_ServiceFilter(service))
    root.addHandler(handler)

    rolling_handler = _RollingLogHandler()
    rolling_handler.setFormatter(formatter)
    rolling_handler.addFilter(_ServiceFilter(service))
    root.addHandler(rolling_handler)
    _configured = True


def get_log_level() -> str:
    """Return current root logger level name."""
    return logging.getLevelName(logging.getLogger().getEffectiveLevel())


def get_recent_log_messages(limit: Optional[int] = None) -> list[str]:
    """Return newest-first formatted log messages from the in-memory ring."""
    with _log_buffer_lock:
        lines = list(_log_buffer)
    lines.reverse()
    if limit is None:
        return lines
    return lines[: max(0, limit)]


def get_log_buffer_capacity() -> int:
    """Return configured in-memory log ring capacity."""
    return _log_buffer.maxlen or 0


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
