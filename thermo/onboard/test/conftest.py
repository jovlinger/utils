"""Pytest config: onboard package on path; smbus stub for tests."""

from __future__ import annotations

import os
import sys

_ONBOARD = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ONBOARD not in sys.path:
    sys.path.insert(0, _ONBOARD)

import smbus_fake

sys.modules["smbus"] = smbus_fake
