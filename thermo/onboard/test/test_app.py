from __future__ import annotations

import pytest

from common.constants import help_msg
from common.heatpumpirctl import State
from hardware.pizero2w import app


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
    assert help_msg == msg


def test_healthz_returns_basic_health_and_recent_logs(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_PATH", "/run/thermo-onboard-log/onboard-app.log")
    client = app.app.test_client()
    app.logger.info("test healthz rolling log marker")

    r = client.get("/healthz?n=5")

    assert r.status_code == 200
    body = r.json
    assert body["ok"] is True
    assert body["service"] == "onboard-app"
    assert body["hardware_backend"] == "pizero2w"
    assert body["log_buffer"]["returned"] == 5
    assert any("test healthz rolling log marker" in line for line in body["log_buffer"]["lines"])
    assert body["log_storage"]["path"] == "/run/thermo-onboard-log/onboard-app.log"


def test_environment_includes_recent_logs_for_dmz_post() -> None:
    client = app.app.test_client()
    app.logger.info("test environment rolling log marker")

    r = client.get("/environment")

    assert r.status_code == 200
    body = r.json
    assert "log_buffer" in body
    assert any("test environment rolling log marker" in line for line in body["log_buffer"]["lines"])


def test_mount_info_for_tmpfs_log_path(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(app.os.path, "exists", lambda _path: True)
    mountinfo = (
        "10 1 0:1 / / rw,relatime - overlay overlay rw\n"
        "20 1 0:2 / /run rw,nosuid,nodev - tmpfs tmpfs rw,size=16384k\n"
    )

    def fake_open(path: str, *args: object, **kwargs: object):
        if path == "/proc/self/mountinfo":
            from io import StringIO

            return StringIO(mountinfo)
        raise AssertionError(path)

    monkeypatch.setattr(app, "open", fake_open, raising=False)

    info = app._mount_info_for_path("/run/thermo-onboard-log/onboard-app.log")

    assert info["mount_point"] == "/run"
    assert info["fs_type"] == "tmpfs"
    assert info["is_tmpfs"] is True


def test_get_daikin_empty_queue_shows_last_applied_default() -> None:
    """GET /daikin with no history returns one row: default off / AUTO / 20°C."""
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
    client = app.app.test_client()
    r = client.get("/daikin")
    assert r.status_code == 200
    assert len(r.json) == 1
    assert r.json[0]["time"] is None
    cmd = r.json[0]["command"]
    assert cmd["power"] is False
    assert cmd["mode"] == "AUTO"
    assert cmd["fan"] == "AUTO"
    assert cmd["half_c"] == 40
    assert cmd["swing"] is False


def test_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment returns rounded temp/humidity from HTU21D (smbus_fake)."""
    monkeypatch.setenv("ENV", "TEST")
    app.HTU21D.instance = None
    res = app.environment()
    assert equalish(37.7, res.get("temperature_centigrade"))
    assert equalish(54.1, res.get("humidity_percent"))


def test_daikin_sequence(send_daikin_spy) -> None:
    """Simple on / uptemp+fan3 / off sequence: POST commands, GET returns newest-first."""
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
    client = app.app.test_client()

    r1 = client.post(
        "/daikin",
        json={"command": {"power": True, "mode": "HEAT", "temp_c": 22, "fan": "AUTO"}},
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
        json={"command": {"power": True, "mode": "HEAT", "temp_c": 23, "fan": "F3"}},
    )
    assert r2.status_code == 200
    assert "environment" in r2.json
    assert r2.json["command"]["half_c"] == 46
    assert r2.json["command"]["fan"] == "F3"

    r3 = client.post(
        "/daikin",
        json={"command": {"power": False, "mode": "HEAT", "temp_c": 23, "fan": "F3"}},
    )
    assert r3.status_code == 200
    assert "environment" in r3.json
    assert not r3.json["command"]["power"]

    get_r = client.get("/daikin")
    assert len(get_r.json) == 3
    assert not get_r.json[0]["command"]["power"]
    assert get_r.json[1]["command"]["fan"] == "F3"
    assert get_r.json[2]["command"]["power"]


def test_daikin_identical_skips_ir(send_daikin_spy) -> None:
    """Repeated identical State must not call send_daikin_state (no duplicate IR)."""
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
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
    assert send_daikin_spy.call_count == 1
    r3 = client.post(
        "/daikin",
        json={"command": {"power": True, "mode": "HEAT", "temp_c": 23, "fan": "AUTO"}},
    )
    assert r3.status_code == 200
    assert r3.json["sent"]
    assert send_daikin_spy.call_count == 2


def test_daikin_uppercase_cli_keys(send_daikin_spy) -> None:
    """CLI-style FAN= / MODE= keys must map to State.from_json field names."""
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
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


def test_daikin_strips_dmz_metadata_keys(send_daikin_spy) -> None:
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
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


def test_daikin_metadata_only_no_ir(monkeypatch: pytest.MonkeyPatch) -> None:
    """DMZ-only keys must not build a default State or call IR."""

    def must_not_send(state: object) -> bool:
        raise AssertionError("send_daikin_state must not run for metadata-only command")

    monkeypatch.setattr(app, "send_daikin_state", must_not_send)
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
    client = app.app.test_client()
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


def test_daikin_twoway_first_post_merges_onto_default(send_daikin_spy) -> None:
    """Zone-shaped body with no prior full POST merges onto cold-start default State.

    Twoway-shaped requests are gated on ``command.created_dt`` strictly newer than
    the onboard-tracked one (None at cold start; first valid command always wins).
    """
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
    app._last_command_created_dt = None
    client = app.app.test_client()
    r = client.post(
        "/daikin",
        json={
            "command": {
                "power": True,
                "fan": "F3",
                "created_dt": "2026-04-19T12:00:00",
            },
            "sensors": {"temp_centigrade": 19.0},
        },
    )
    assert r.status_code == 200
    assert r.json["sent"]
    c = r.json["command"]
    assert c["power"] is True
    assert c["fan"] == "F3"
    assert c["mode"] == "AUTO"
    assert c["half_c"] == 40
    assert send_daikin_spy.call_count == 1


def test_daikin_twoway_merge_partial_into_last_state(send_daikin_spy) -> None:
    """Zone-shaped body (sensors present) merges partial command onto last applied State.

    The second twoway POST must carry a strictly-newer ``created_dt`` than the first
    UI-direct command (which receiver-stamped at receive time).
    """
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
    app._last_command_created_dt = None
    client = app.app.test_client()
    r1 = client.post(
        "/daikin",
        json={"command": {"power": True, "mode": "HEAT", "temp_c": 21, "fan": "AUTO"}},
    )
    assert r1.status_code == 200
    assert r1.json["sent"]
    # Use far-future timestamp so the gate accepts regardless of how fast we run.
    r2 = client.post(
        "/daikin",
        json={
            "command": {"fan": "F3", "created_dt": "2099-01-01T00:00:00"},
            "sensors": {"temp_centigrade": 20.0},
        },
    )
    assert r2.status_code == 200
    assert r2.json["command"]["mode"] == "HEAT"
    assert r2.json["command"]["fan"] == "F3"
    assert send_daikin_spy.call_count == 2


def test_daikin_twoway_obsolete_command_ignored(send_daikin_spy) -> None:
    """Twoway command with non-newer created_dt must NOT touch IR or last-applied state."""
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
    app._last_command_created_dt = None
    client = app.app.test_client()
    r1 = client.post(
        "/daikin",
        json={"command": {"power": True, "mode": "HEAT", "temp_c": 22, "fan": "AUTO"}},
    )
    assert r1.status_code == 200
    assert r1.json["sent"]
    sends_after_first = send_daikin_spy.call_count
    tracked_after_first = app._last_command_created_dt
    assert tracked_after_first is not None

    # Same created_dt as tracked -> NOT strictly newer -> obsolete.
    r_eq = client.post(
        "/daikin",
        json={
            "command": {"fan": "F3", "created_dt": tracked_after_first},
            "sensors": {"temp_centigrade": 20.0},
        },
    )
    assert r_eq.status_code == 200
    assert r_eq.json["sent"] is False
    assert "obsolete" in r_eq.json.get("reason", "")
    assert send_daikin_spy.call_count == sends_after_first
    assert app._last_command_created_dt == tracked_after_first

    # Older created_dt -> obsolete.
    r_old = client.post(
        "/daikin",
        json={
            "command": {"fan": "F3", "created_dt": "1999-01-01T00:00:00"},
            "sensors": {"temp_centigrade": 20.0},
        },
    )
    assert r_old.status_code == 200
    assert r_old.json["sent"] is False
    assert "obsolete" in r_old.json.get("reason", "")
    assert send_daikin_spy.call_count == sends_after_first

    # Missing created_dt on twoway path -> obsolete (cannot prove newer).
    r_miss = client.post(
        "/daikin",
        json={
            "command": {"fan": "F3"},
            "sensors": {"temp_centigrade": 20.0},
        },
    )
    assert r_miss.status_code == 200
    assert r_miss.json["sent"] is False
    assert "obsolete" in r_miss.json.get("reason", "")
    assert send_daikin_spy.call_count == sends_after_first


def test_environment_includes_command_with_created_dt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /environment exposes the last-applied command + created_dt for twoway to forward."""
    monkeypatch.setenv("ENV", "TEST")
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
    app._last_command_created_dt = None
    client = app.app.test_client()

    r0 = client.get("/environment")
    assert r0.status_code == 200
    assert r0.json["command"] is None  # cold start: no command yet

    client.post(
        "/daikin",
        json={"command": {"power": True, "mode": "COOL", "temp_c": 24, "fan": "AUTO"}},
    )
    r1 = client.get("/environment")
    assert r1.status_code == 200
    cmd = r1.json["command"]
    assert isinstance(cmd, dict)
    assert cmd["mode"] == "COOL"
    assert isinstance(cmd.get("created_dt"), str) and cmd["created_dt"]


def test_manage_get_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANAGE_TOKEN", "test-token")
    client = app.app.test_client()
    r = client.get("/manage", headers={"X-Manage-Token": "test-token"})
    assert r.status_code == 200
    assert "pid" in r.json
    assert "log_level" in r.json
    assert "fake_sensor" in r.json
    assert r.json["deployment"]["hardware_profile"] == "pi_zero_2w_htu21d_ir"


def test_manage_set_log_level(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANAGE_TOKEN", "test-token")
    client = app.app.test_client()
    r = client.post(
        "/manage",
        json={"action": "set_log_level", "level": "debug"},
        headers={"X-Manage-Token": "test-token"},
    )
    assert r.status_code == 200
    assert r.json["level"] == "DEBUG"


def test_manage_inject_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANAGE_TOKEN", "test-token")
    client = app.app.test_client()
    r = client.post(
        "/manage",
        json={"action": "inject_log", "level": "INFO", "message": "hello"},
        headers={"X-Manage-Token": "test-token"},
    )
    assert r.status_code == 200
    assert r.json["action"] == "inject_log"
    assert r.json["message"] == "hello"


def test_manage_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MANAGE_TOKEN", "test-token")
    client = app.app.test_client()
    r = client.post(
        "/manage",
        json={"action": "raise", "message": "boom"},
        headers={"X-Manage-Token": "test-token"},
    )
    assert r.status_code == 500


def test_ui_context_single_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /ui/context exposes one zone name and matches environment + latest command."""
    monkeypatch.setenv("ENV", "TEST")
    monkeypatch.setenv("ZONE_NAME", "pizero")
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
    client = app.app.test_client()
    client.post(
        "/daikin",
        json={"command": {"power": True, "mode": "COOL", "temp_c": 24, "fan": "AUTO"}},
    )
    r = client.get("/ui/context")
    assert r.status_code == 200
    js = r.json
    assert js["zones"] == ["pizero"]
    assert len(js["environments"]) == 1
    assert js["environments"][0]["zone"] == "pizero"
    assert js["environments"][0]["temperature_centigrade"] is not None
    assert js["zone_states"]["pizero"]["command"]["mode"] == "COOL"
    assert js["zone_states"]["pizero"]["sensors"] is None
    assert js["deployment"]["zone_name"] == "pizero"
    assert js["deployment"]["send_behavior"] == "ir_daikin"


def test_ui_command_matches_daikin(monkeypatch: pytest.MonkeyPatch) -> None:
    """POST /ui/command applies the same way as POST /daikin for a bare command."""
    monkeypatch.setenv("ENV", "TEST")
    app.daikin_cmds.clear()
    app._last_daikin_ir_fingerprint = None
    app._last_applied_state = State()
    client = app.app.test_client()
    r = client.post(
        "/ui/command",
        json={
            "zone": "ignored",
            "command": {"power": True, "mode": "HEAT", "temp_c": 21},
        },
    )
    assert r.status_code == 200
    assert r.json["zone"] == "default"
    assert r.json["command"]["mode"] == "HEAT"
    assert r.json["sent"] is True
    assert r.json["sensors"] is None
