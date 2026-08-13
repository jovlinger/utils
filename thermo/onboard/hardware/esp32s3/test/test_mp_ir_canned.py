"""Host tests for canned Midea IR on/off bootstrap."""

from __future__ import annotations

import sys
from pathlib import Path

MP_DIR = Path(__file__).resolve().parents[1] / "mp"
sys.path.insert(0, str(MP_DIR))

import ir_canned  # noqa: E402
from main import DebugApp  # noqa: E402


def test_canned_on_matches_pico_office_cool_on_frame() -> None:
    hexes = ir_canned.frames_hex(True)
    assert hexes[0] == ir_canned.ON_STATE_HEX
    assert hexes[1] == ir_canned.ON_STATE_HEX
    assert len(hexes) == 3  # state x2 + D5 secondary
    assert hexes[2].startswith("D5")


def test_canned_off_matches_pico_office_cool_off_frame() -> None:
    hexes = ir_canned.frames_hex(False)
    assert hexes[0] == ir_canned.OFF_STATE_HEX
    assert hexes[1] == ir_canned.OFF_STATE_HEX
    assert len(hexes) == 2  # no secondary when power off


def test_http_ir_on_off_dry_run() -> None:
    app = DebugApp(ir_dry_run=True)
    st, body = app.handle_path("/ir/on")
    assert st == 200
    assert body["ok"] is True
    assert body["action"] == "ir_canned_on"
    assert body["frames_hex"][0] == ir_canned.ON_STATE_HEX
    assert body["tx_mode"] == "dry_run"
    assert body["tx_pairs"] > 0

    st, body = app.handle_path("/ir/off")
    assert st == 200
    assert body["action"] == "ir_canned_off"
    assert body["frames_hex"][0] == ir_canned.OFF_STATE_HEX
    assert body["tx_mode"] == "dry_run"


def test_upload_manifest_includes_midea_omits_daikin() -> None:
    manifest = (
        Path(__file__).resolve().parents[1] / "install" / "upload.manifest"
    ).read_text(encoding="ascii")
    assert "ir_midea.py" in manifest
    assert "ir_canned.py" in manifest
    assert "ir_tx.py" in manifest
    assert "ir_daikin.py" not in manifest
