"""Assign every collected test a tier marker. Rules live in `tiering`."""

from __future__ import annotations

import pytest

import tiering


def pytest_collection_modifyitems(items):
    for item in items:
        declared = {m.name for m in item.iter_markers()}
        tier = tiering.tier_for(getattr(item, "cls", None), declared)
        if tier not in declared:
            item.add_marker(getattr(pytest.mark, tier))
