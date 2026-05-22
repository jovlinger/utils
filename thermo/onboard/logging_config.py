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
