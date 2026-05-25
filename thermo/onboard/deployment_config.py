"""Compatibility wrapper for onboard deployment configuration."""

from __future__ import annotations

import sys

from common import deployment_config as _impl

sys.modules[__name__] = _impl
