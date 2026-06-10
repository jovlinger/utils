from __future__ import annotations

import sys
from pathlib import Path

_UI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_UI))

import ui_server  # noqa: E402


def test_zone_logs_html_renders_selected_zone_tail() -> None:
    ctx = {
        "zone_states": {
            "office": {
                "logs": {
                    "received_dt": "2026-05-27T01:00:03Z",
                    "lines": [
                        "2026-05-27T01:00:01.000Z INFO onboard action taken",
                        "2026-05-27T01:00:02.000Z DEBUG onboard command stale",
                    ],
                }
            },
            "kitchen": {"logs": {"lines": ["wrong zone"]}},
        }
    }

    rendered = ui_server._zone_logs_html(ctx, "office")

    assert "action taken" in rendered
    assert "command stale" in rendered
    assert "wrong zone" not in rendered
