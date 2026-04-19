"""
Standard functions used everywhere. Logging configured for app and twoway.
"""

from __future__ import annotations

import logging
import os
import sys
import time
from typing import Any, Optional, Union

# Parsed HTTP JSON body from onboard helpers: object -> dict, else raw text.
jsonT = Union[dict, str]

# possibly the least informative name ever
ENVVAR = "ENV"


def is_test_env() -> bool:
    """Are we running in a test environment?"""
    return os.environ.get(ENVVAR) in ["TEST", "DOCKERTEST"]


# ---------------------------------------------------------------------------
# Logging: same wire format as DMZ (UTC ISO millis + level + message)
# ---------------------------------------------------------------------------


LOG_LEVEL = os.environ.get("LOG_LEVEL", "DEBUG").upper()
LOG_PATH = os.environ.get("LOG_PATH")
LOGGER_NAME = "onboard"
_VALID_LOG_LEVELS = {
    "CRITICAL": logging.CRITICAL,
    "ERROR": logging.ERROR,
    "WARNING": logging.WARNING,
    "INFO": logging.INFO,
    "DEBUG": logging.DEBUG,
    "NOTSET": logging.NOTSET,
}


def configure_logging() -> None:
    """
    Configure onboard logger with the DMZ format.

    Output goes to stdout so `run-with-stdout-logged.py` can handle file writing
    and rotation uniformly for both DMZ and onboard.
    """
    root = logging.getLogger(LOGGER_NAME)
    root.setLevel(_VALID_LOG_LEVELS.get(LOG_LEVEL, logging.DEBUG))
    root.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s.%(msecs)03dZ %(levelname)s %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    formatter.converter = time.gmtime

    h = logging.StreamHandler(sys.stdout)
    h.setFormatter(formatter)
    root.addHandler(h)
    root.propagate = False


def get_log_level() -> str:
    """Return current onboard logger level name."""
    logger = logging.getLogger(LOGGER_NAME)
    return logging.getLevelName(logger.getEffectiveLevel())


def set_log_level(level_name: str) -> Optional[str]:
    """Set onboard logger level from name. Returns normalized level or None."""
    if not level_name:
        return None
    normalized = level_name.upper().strip()
    level = _VALID_LOG_LEVELS.get(normalized)
    if level is None:
        return None
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(level)
    return normalized


configure_logging()


def _emit(component: str, msg: str, level: int, **kwargs: Any) -> None:
    extra = " " + " ".join(f"{k}={v!r}" for k, v in kwargs.items()) if kwargs else ""
    logging.getLogger(LOGGER_NAME).log(level, "%s: %s%s", component, msg, extra)


def log(component: str, msg: str, **kwargs: Any) -> None:
    """Single-line log at INFO. component is e.g. 'app', 'twoway', or 'ir'."""
    _emit(component, msg, logging.INFO, **kwargs)


def log_error(component: str, msg: str, **kwargs: Any) -> None:
    """Same wire format as log, at ERROR level."""
    _emit(component, msg, logging.ERROR, **kwargs)


def log_warning(component: str, msg: str, **kwargs: Any) -> None:
    """Same wire format as log, at WARNING level."""
    _emit(component, msg, logging.WARNING, **kwargs)


def log_debug(component: str, msg: str, **kwargs: Any) -> None:
    """Same wire format as log, at DEBUG level."""
    _emit(component, msg, logging.DEBUG, **kwargs)
