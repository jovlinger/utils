from __future__ import annotations

import sys
from pathlib import Path

_UI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_UI))

import ui_server  # noqa: E402


def test_collapsible_log_block_shows_all_when_short() -> None:
    lines = [f"line {i}" for i in range(5)]
    rendered = ui_server._collapsible_log_block(lines, visible=20)
    assert "<details" not in rendered
    assert "line 4" in rendered


def test_collapsible_log_block_hides_tail_when_long() -> None:
    lines = [f"line {i}" for i in range(25)]
    rendered = ui_server._collapsible_log_block(lines, visible=20)
    assert "line 19" in rendered
    assert "line 20" not in rendered.split("</summary>")[0]
    assert "<details" in rendered
    assert "5 more lines" in rendered
    assert "line 24" in rendered


def test_zone_logs_html_collapses_long_tail() -> None:
    ctx = {
        "zone_states": {
            "office": {
                "logs": {
                    "received_dt": "2026-05-27T01:00:03Z",
                    "lines": [f"2026-05-27T01:00:01.000Z INFO onboard line {i}" for i in range(25)],
                }
            }
        }
    }

    rendered = ui_server._zone_logs_html(ctx, "office")

    assert "last reported" in rendered
    assert "<details" in rendered
    assert "5 more lines" in rendered
