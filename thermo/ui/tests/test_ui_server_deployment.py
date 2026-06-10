from __future__ import annotations

import sys
from pathlib import Path

_UI = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_UI))

import ui_server  # noqa: E402


def test_env_table_rows_include_hardware_and_git() -> None:
    ctx = {
        "environments": [
            {
                "zone": "kitchen",
                "temperature_centigrade": 21.0,
                "humidity_percent": 50.0,
                "time": "2026-05-27T01:00:00",
                "deployment": {
                    "hardware_profile": "pico2w_aht20_ir",
                    "git_sha_short": "deadbeef",
                },
            }
        ]
    }

    rendered = ui_server._env_table_rows(ctx)

    assert "pico2w_aht20_ir" in rendered
    assert "deadbeef" in rendered
    assert "<th>Hardware</th>" not in rendered


def test_zone_deployment_html_renders_selected_zone() -> None:
    ctx = {
        "zone_states": {
            "office": {
                "deployment": {
                    "received_dt": "2026-05-27T01:00:03Z",
                    "hardware_profile": "pi_zero_2w_htu21d_ir",
                    "git_sha": "abcdef1234567890",
                    "backend": "pizero2w",
                }
            },
            "kitchen": {
                "deployment": {
                    "hardware_profile": "pico2w_aht20_ir",
                    "git_sha_short": "cafebabe",
                }
            },
        }
    }

    rendered = ui_server._zone_deployment_html(ctx, "office")

    assert "pi_zero_2w_htu21d_ir" in rendered
    assert "abcdef1234567890" in rendered
    assert "pico2w_aht20_ir" not in rendered
