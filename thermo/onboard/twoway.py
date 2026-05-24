"""Compatibility entrypoint for the Pi Zero 2 W twoway process."""

from __future__ import annotations

import sys

from common import twoway as _impl

sys.modules[__name__] = _impl

if __name__ == "__main__":
    _impl.main()
