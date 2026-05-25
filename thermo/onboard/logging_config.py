"""Compatibility wrapper for onboard logging configuration."""

from __future__ import annotations

import sys

from common import logging_config as _impl

sys.modules[__name__] = _impl
