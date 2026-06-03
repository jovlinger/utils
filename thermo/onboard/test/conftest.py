"""Pytest config: onboard package on path; smbus stub; IR send spy fixture."""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

_ONBOARD = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ONBOARD not in sys.path:
    sys.path.insert(0, _ONBOARD)

from hardware.pizero2w import smbus_fake

sys.modules["smbus"] = smbus_fake

from hardware.pizero2w import app as app_module


class DaikinSendSpy:
    """Records heat-pump IR send calls; returns ``return_value`` each time."""

    def __init__(self, return_value: bool = True) -> None:
        self.return_value = return_value
        self.call_count = 0

    def __call__(self, state: Any) -> bool:
        self.call_count += 1
        return self.return_value


@pytest.fixture
def send_daikin_spy(monkeypatch: pytest.MonkeyPatch) -> DaikinSendSpy:
    spy = DaikinSendSpy()
    monkeypatch.setattr(app_module, "send_heatpump_state", spy)
    return spy
