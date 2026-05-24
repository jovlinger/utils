"""Compatibility wrapper for the shared heat-pump IR package."""

from __future__ import annotations

import sys

from common import heatpumpirctl as _impl

sys.modules[__name__] = _impl
