"""Compatibility wrapper for the shared ARC452A9 protocol module."""

from __future__ import annotations

import sys

from common.heatpumpirctl import ARC452A9 as _impl

sys.modules[__name__] = _impl
