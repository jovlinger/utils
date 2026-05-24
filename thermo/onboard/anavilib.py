"""Compatibility wrapper for Pi Zero 2 W ANAVI hardware helpers."""

from __future__ import annotations

import sys

from hardware.pizero2w import anavilib as _impl

sys.modules[__name__] = _impl
