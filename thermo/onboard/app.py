"""Compatibility entrypoint for the Pi Zero 2 W onboard app."""

from __future__ import annotations

import sys

from hardware.pizero2w import app as _impl

sys.modules[__name__] = _impl

if __name__ == "__main__":
    _impl.main()
