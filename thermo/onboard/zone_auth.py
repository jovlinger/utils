"""Compatibility wrapper for onboard zone authentication helpers."""

from __future__ import annotations

import sys

from common import zone_auth as _impl

sys.modules[__name__] = _impl
