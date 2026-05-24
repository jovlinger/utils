"""Compatibility wrapper for onboard constants."""

from __future__ import annotations

import sys

from common import constants as _impl

sys.modules[__name__] = _impl
