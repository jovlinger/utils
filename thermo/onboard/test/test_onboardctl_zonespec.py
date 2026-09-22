"""Tests for onboardctl zonespec parse/resolve."""

from __future__ import annotations

from pathlib import Path

import pytest

# Import from onboardctl package directory.
import sys

ONBOARDCTL_DIR = Path(__file__).resolve().parents[1] / "onboardctl"
sys.path.insert(0, str(ONBOARDCTL_DIR))

from zonespec import (  # noqa: E402
    parse_zonespec,
    load_targets_from_zones_dir,
    resolve_zonespec,
)


ZONES = Path(__file__).resolve().parents[1] / "zones"


def test_parse_bare_zone_defaults_kind() -> None:
    spec = parse_zonespec("office")
    assert spec.kind == "zone"
    assert spec.value == "office"


def test_parse_prefixed_kinds() -> None:
    assert parse_zonespec("hardware:esp32").kind == "hardware"
    assert parse_zonespec("dialect:midea").value == "midea"
    assert parse_zonespec("type:ac").kind == "type"


def test_resolve_zone_office() -> None:
    targets = load_targets_from_zones_dir(ZONES)
    matched = resolve_zonespec(parse_zonespec("office"), targets)
    assert len(matched) == 1
    assert matched[0].zone_name == "office"
    assert "esp32" in matched[0].backend or "esp32" in matched[0].hardware_profile


def test_hardware_esp32_matches_all_esp32_family() -> None:
    targets = load_targets_from_zones_dir(ZONES)
    matched = resolve_zonespec(parse_zonespec("hardware:esp32"), targets)
    assert matched, "expected at least office esp32s3"
    assert all("esp32" in t.backend or "esp32" in t.hardware_profile for t in matched)


def test_hardware_esp32s3_is_narrower_or_equal() -> None:
    targets = load_targets_from_zones_dir(ZONES)
    broad = resolve_zonespec(parse_zonespec("hardware:esp32"), targets)
    narrow = resolve_zonespec(parse_zonespec("hardware:esp32s3"), targets)
    assert set(t.zone_name for t in narrow) <= set(t.zone_name for t in broad)


def test_dialect_midea_matches_office() -> None:
    targets = load_targets_from_zones_dir(ZONES)
    matched = resolve_zonespec(parse_zonespec("dialect:midea"), targets)
    assert any(t.zone_name == "office" for t in matched)


def test_parse_all_is_pseudo() -> None:
    spec = parse_zonespec("ALL")
    assert spec.kind == "all"
    assert str(spec) == "ALL"
    assert parse_zonespec("all").kind == "all"


def test_resolve_all_returns_every_zone_env() -> None:
    targets = load_targets_from_zones_dir(ZONES)
    matched = resolve_zonespec(parse_zonespec("ALL"), targets)
    assert matched == targets
    assert {t.zone_name for t in matched} >= {"office", "kitchen", "bedroom"}
