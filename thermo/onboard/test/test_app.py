from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import app
import constants


def equalish(a: object, b: object) -> bool:
    if isinstance(a, dict):
        return equalish_dict(a, b)
    if isinstance(a, float):
        return equalish_float(a, b)
    return a == b


def equalish_dict(a: dict, b: object) -> bool:
    if not isinstance(b, dict):
        return False
    if len(a) != len(b):
        return False
    for k, va in a.items():
        vb = b[k]
        if not equalish(va, vb):
            return False
    return True


epsilon = 0.01


def equalish_float(a: float, b: object) -> bool:
    if isinstance(b, (int, float)):
        return abs(a - float(b)) < epsilon
    return False


def test_help() -> None:
    """Test using local call."""
    msg = app.help().get("msg")
    assert constants.help_msg == msg


def test_environment() -> None:
    """Environment returns rounded temp/humidity from HTU21D (smbus_fake)."""
    with patch.dict(os.environ, {"ENV": "TEST"}, clear=False):
        app.HTU21D.instance = None
        res = app.environment()
    assert equalish(37.7, res.get("temperature_centigrade"))
    assert equalish(54.1, res.get("humidity_percent"))


@patch("app.send_daikin_state", return_value=True)
def test_daikin_sequence(_mock_send: MagicMock) -> None:
    """Simple on / uptemp+fan3 / off sequence: POST commands, GET returns newest-first."""
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = None
    client = app.app.test_client()

    r1 = client.post(
        "/daikin",
        json={
            "command": {"power": True, "mode": "HEAT", "temp_c": 22, "fan": "AUTO"}
        },
    )
    assert r1.status_code == 200
    assert r1.json["sent"]
    assert "environment" in r1.json
    assert "temperature_centigrade" in r1.json["environment"]
    assert r1.json["command"]["power"]
    assert r1.json["command"]["mode"] == "HEAT"
    assert r1.json["command"]["half_c"] == 44

    r2 = client.post(
        "/daikin",
        json={
            "command": {"power": True, "mode": "HEAT", "temp_c": 23, "fan": "F3"}
        },
    )
    assert r2.status_code == 200
    assert "environment" in r2.json
    assert r2.json["command"]["half_c"] == 46
    assert r2.json["command"]["fan"] == "F3"

    r3 = client.post(
        "/daikin",
        json={
            "command": {"power": False, "mode": "HEAT", "temp_c": 23, "fan": "F3"}
        },
    )
    assert r3.status_code == 200
    assert "environment" in r3.json
    assert not r3.json["command"]["power"]

    get_r = client.get("/daikin")
    assert len(get_r.json) == 3
    assert not get_r.json[0]["command"]["power"]
    assert get_r.json[1]["command"]["fan"] == "F3"
    assert get_r.json[2]["command"]["power"]


@patch("app.send_daikin_state", return_value=True)
def test_daikin_identical_skips_ir(mock_send: MagicMock) -> None:
    """Repeated identical State must not call send_daikin_state (no duplicate IR)."""
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = None
    client = app.app.test_client()
    body = {"command": {"power": True, "mode": "HEAT", "temp_c": 22, "fan": "AUTO"}}
    r1 = client.post("/daikin", json=body)
    assert r1.status_code == 200
    assert r1.json["sent"]
    assert "unchanged" not in r1.json
    r2 = client.post("/daikin", json=body)
    assert r2.status_code == 200
    assert not r2.json["sent"]
    assert r2.json.get("unchanged")
    assert "environment" in r2.json
    assert mock_send.call_count == 1
    r3 = client.post(
        "/daikin",
        json={"command": {"power": True, "mode": "HEAT", "temp_c": 23, "fan": "AUTO"}},
    )
    assert r3.status_code == 200
    assert r3.json["sent"]
    assert mock_send.call_count == 2


@patch("app.send_daikin_state", return_value=True)
def test_daikin_uppercase_cli_keys(mock_send: MagicMock) -> None:
    """CLI-style FAN= / MODE= keys must map to State.from_json field names."""
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = None
    client = app.app.test_client()
    r = client.post(
        "/daikin",
        json={
            "command": {
                "POWER": True,
                "MODE": "HEAT",
                "HALF_C": 44,
                "FAN": "F1",
            }
        },
    )
    assert r.status_code == 200
    assert r.json["sent"]
    assert r.json["command"]["fan"] == "F1"
    assert r.json["command"]["mode"] == "HEAT"


@patch("app.send_daikin_state", return_value=True)
def test_daikin_strips_dmz_metadata_keys(mock_send: MagicMock) -> None:
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = None
    client = app.app.test_client()
    r = client.post(
        "/daikin",
        json={
            "command": {
                "fan": "F4",
                "created_dt": "2026-01-01T00:00:00",
                "last_access_dt": "2026-01-02T00:00:00",
            }
        },
    )
    assert r.status_code == 200
    assert r.json["sent"]
    assert r.json["command"]["fan"] == "F4"


def test_daikin_metadata_only_no_ir() -> None:
    """DMZ-only keys must not build a default State or call IR."""
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = None
    client = app.app.test_client()
    with patch("app.send_daikin_state") as mock_send:
        r = client.post(
            "/daikin",
            json={
                "command": {
                    "created_dt": "x",
                    "last_access_dt": "y",
                }
            },
        )
    assert r.status_code == 200
    assert not r.json["sent"]
    assert r.json.get("reason") == "no state fields in command"
    assert "environment" in r.json
    mock_send.assert_not_called()


@patch("app.send_daikin_state", return_value=True)
def test_daikin_twoway_merge_partial_into_last_state(mock_send: MagicMock) -> None:
    """Zone-shaped body (sensors present) merges partial command onto last applied State."""
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = None
    client = app.app.test_client()
    r1 = client.post(
        "/daikin",
        json={"command": {"power": True, "mode": "HEAT", "temp_c": 21, "fan": "AUTO"}},
    )
    assert r1.status_code == 200
    assert r1.json["sent"]
    r2 = client.post(
        "/daikin",
        json={
            "command": {"fan": "F3"},
            "sensors": {"temp_centigrade": 20.0},
        },
    )
    assert r2.status_code == 200
    assert r2.json["command"]["mode"] == "HEAT"
    assert r2.json["command"]["fan"] == "F3"
    assert mock_send.call_count == 2


def test_manage_get_state() -> None:
    client = app.app.test_client()
    with patch.dict(os.environ, {"MANAGE_TOKEN": "test-token"}, clear=False):
        r = client.get("/manage", headers={"X-Manage-Token": "test-token"})
    assert r.status_code == 200
    assert "pid" in r.json
    assert "log_level" in r.json
    assert "fake_sensor" in r.json


def test_manage_set_log_level() -> None:
    client = app.app.test_client()
    with patch.dict(os.environ, {"MANAGE_TOKEN": "test-token"}, clear=False):
        r = client.post(
            "/manage",
            json={"action": "set_log_level", "level": "debug"},
            headers={"X-Manage-Token": "test-token"},
        )
    assert r.status_code == 200
    assert r.json["level"] == "DEBUG"


def test_manage_inject_log() -> None:
    client = app.app.test_client()
    with patch.dict(os.environ, {"MANAGE_TOKEN": "test-token"}, clear=False):
        r = client.post(
            "/manage",
            json={"action": "inject_log", "level": "INFO", "message": "hello"},
            headers={"X-Manage-Token": "test-token"},
        )
    assert r.status_code == 200
    assert r.json["action"] == "inject_log"
    assert r.json["message"] == "hello"


def test_manage_raise() -> None:
    client = app.app.test_client()
    with patch.dict(os.environ, {"MANAGE_TOKEN": "test-token"}, clear=False):
        r = client.post(
            "/manage",
            json={"action": "raise", "message": "boom"},
            headers={"X-Manage-Token": "test-token"},
        )
    assert r.status_code == 500
