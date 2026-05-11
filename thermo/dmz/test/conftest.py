"""Pytest config: DMZ app on path and optional Flask app_context."""

from __future__ import annotations

import os
import sys

_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from typing import Iterator

import pytest

import app as dmz_module
from app import app as dmz_application


@pytest.fixture
def dmz_ctx() -> Iterator[None]:
    ctx = dmz_application.app_context()
    ctx.push()
    try:
        yield
    finally:
        ctx.pop()


@pytest.fixture
def restore_zone_public_key() -> Iterator[None]:
    orig = os.environ.get("ZONE_PUBLIC_KEY")
    yield
    if orig is not None:
        os.environ["ZONE_PUBLIC_KEY"] = orig
    else:
        os.environ.pop("ZONE_PUBLIC_KEY", None)


@pytest.fixture(autouse=True)
def fast_long_poll_defaults(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """
    Keep tests fast: default zone long-poll timeout is disabled unless a test opts in.
    """
    monkeypatch.setattr(dmz_module, "LONG_POLL_TIMEOUT_SECS", 0.0)
    monkeypatch.setattr(dmz_module, "LONG_POLL_SLEEP_SECS", 0.001)
    yield
