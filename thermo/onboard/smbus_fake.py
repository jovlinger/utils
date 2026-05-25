"""Compatibility wrapper for Pi Zero 2 W SMBus test fake."""

from __future__ import annotations

import sys

from hardware.pizero2w import smbus_fake as _impl

sys.modules[__name__] = _impl
