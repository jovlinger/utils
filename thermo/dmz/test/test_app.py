"""DMZ app tests: unit tests and happy-path integration tests."""

from __future__ import annotations

import json
import os
from typing import Any

from app import app


def _pathget(d: dict, path: str) -> Any:
    """Get nested dict value by dot-separated path, e.g. 'command.mode'."""
    cur: Any = d
    for key in path.split("."):
        cur = cur.get(key, {}) if isinstance(cur, dict) else cur
    return cur


def _post_200(c, url: str, body: dict) -> dict:
    res = c.post(url, json=body)
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json() or {}


def _get_200(c, url: str) -> dict:
    res = c.get(url)
    assert res.status_code == 200, res.get_data(as_text=True)
    return res.get_json() or {}


def _reset(c, commands: dict | None = None, sensors: dict | None = None) -> None:
    _post_200(c, "/test_reset", {"commands": commands or {}, "sensors": sensors or {}})


def test_update_sensors_and_command_multi_zone(dmz_ctx: object) -> None:
    """Multiple zones: update sensors/commands, verify last_access_dt and latest values."""
    with app.test_client() as c:
        _reset(c)
        _post_200(c, "/zone/z1/command", {"power": True, "mode": "HEAT"})
        _post_200(c, "/zone/z1/sensors", {"temp_centigrade": 11.45})
        _post_200(
            c,
            "/zone/z2/sensors",
            {"temp_centigrade": 21.34, "humid_percent": 99.99},
        )
        js12 = _post_200(c, "/zone/z1/command", {"power": True, "mode": "COOL"})
        _post_200(c, "/zone/z3/command", {"power": False})

        js13 = _post_200(c, "/zone/z1/sensors", {"temp_centigrade": 13.34})

        assert (
            js12["command"]["last_access_dt"] != js13["command"]["last_access_dt"]
        ), "Expected access times to be updated on /zone/ endpoint"
        assert js13["command"]["mode"] == "COOL"
        assert js13["sensors"]["temp_centigrade"] == 13.34

        js = _get_200(c, "/zones")
        assert sorted(js.keys()) == ["z1", "z2", "z3"]
        assert js["z1"] == js13


def test_empty_command_overwrites_then_new_command(dmz_ctx: object) -> None:
    """POST command replaces previous; empty body ({}) is stored as-is."""
    with app.test_client() as c:
        _reset(c)
        _post_200(c, "/zone/z1/command", {"power": True, "mode": "HEAT"})
        _post_200(c, "/zone/z1/command", {})
        js = _get_200(c, "/zones")
        assert "mode" not in js["z1"]["command"]
        _post_200(c, "/zone/z1/command", {"power": True, "mode": "COOL"})
        js = _get_200(c, "/zones")
        assert _pathget(js["z1"], "command.mode") == "COOL"


def test_command_rejects_invalid_json(dmz_ctx: object) -> None:
    """POST /zone/.../command returns 400 when body is not valid JSON."""
    with app.test_client() as c:
        _reset(c)
        r = c.post(
            "/zone/z1/command",
            data="{not json",
            content_type="application/json",
        )
        assert r.status_code == 400
        js = r.get_json() or {}
        assert js.get("error") == "invalid JSON"


def test_command_rejects_empty_body(dmz_ctx: object) -> None:
    with app.test_client() as c:
        _reset(c)
        r = c.post("/zone/z1/command", data="", content_type="application/json")
        assert r.status_code == 400
        assert (r.get_json() or {}).get("error") == "empty body"


def test_command_rejects_non_ascii_string(dmz_ctx: object) -> None:
    """JSON string values must be 7-bit ASCII only."""
    with app.test_client() as c:
        _reset(c)
        r = c.post(
            "/zone/z1/command",
            data='{"mode": "\\u00e9"}',
            content_type="application/json",
        )
        assert r.status_code == 400
        err = (r.get_json() or {}).get("error", "")
        assert "ASCII" in err


def test_command_rejects_non_ascii_object_key(dmz_ctx: object) -> None:
    with app.test_client() as c:
        _reset(c)
        r = c.post(
            "/zone/z1/command",
            data='{"\\u00e9": "x"}',
            content_type="application/json",
        )
        assert r.status_code == 400


def test_command_accepts_arbitrary_object_keys(dmz_ctx: object) -> None:
    """Command body may include any ASCII-only keys on a JSON object."""
    with app.test_client() as c:
        _reset(c)
        body = {"mode": "HEAT", "power": True, "temp_c": 21}
        js = _post_200(c, "/zone/z1/command", body)
        assert js["command"]["mode"] == "HEAT"
        assert js["command"]["power"] is True
        assert js["command"]["temp_c"] == 21


def _onboard_post_sensors(
    c, zone: str, temp: float, humid: float | None = None
) -> dict:
    body: dict = {"temp_centigrade": temp}
    if humid is not None:
        body["humid_percent"] = humid
    return c.post(f"/zone/{zone}/sensors", json=body).get_json() or {}


def test_onboard_zones_poll_sensors_receive_commands(dmz_ctx: object) -> None:
    """
    External client sets command for z1. Onboard z1 posts sensors, receives command.
    Onboard z2 posts sensors, has no command. External client sets command for z2.
    """
    with app.test_client() as c:
        c.post("/test_reset", json={"commands": {}, "sensors": {}})
        _post_200(c, "/zone/z1/command", {"power": True, "mode": "HEAT"})

        r1 = _onboard_post_sensors(c, "z1", 19.5, 45.0)
        assert r1["command"]["mode"] == "HEAT"
        assert r1["sensors"]["temp_centigrade"] == 19.5
        assert r1["sensors"]["humid_percent"] == 45.0

        r2 = _onboard_post_sensors(c, "z2", 21.0)
        assert r2.get("command") is None

        _post_200(c, "/zone/z2/command", {"power": True, "mode": "COOL"})

        r3 = _onboard_post_sensors(c, "z2", 21.2)
        assert r3["command"]["mode"] == "COOL"


def test_onboard_multiple_zones_independent(dmz_ctx: object) -> None:
    """Multiple onboard instances: each zone's sensors and commands are independent."""
    with app.test_client() as c:
        c.post("/test_reset", json={"commands": {}, "sensors": {}})
        _post_200(
            c, "/zone/living/command", {"power": True, "mode": "HEAT", "temp_c": 22}
        )
        _post_200(c, "/zone/bedroom/command", {"power": False})

        living = _onboard_post_sensors(c, "living", 20.1, 50.0)
        bedroom = _onboard_post_sensors(c, "bedroom", 18.5, 55.0)

        assert living["command"]["mode"] == "HEAT"
        assert bedroom["command"]["power"] is False
        assert living["sensors"]["temp_centigrade"] == 20.1
        assert bedroom["sensors"]["temp_centigrade"] == 18.5


def test_external_client_reads_state_updates_commands(dmz_ctx: object) -> None:
    """
    Onboard zones have posted sensors. External client GETs /zones, sees state.
    External client POSTs commands. Next onboard poll will receive them.
    """
    with app.test_client() as c:
        c.post("/test_reset", json={"commands": {}, "sensors": {}})
        c.post(
            "/zone/z1/sensors",
            json={"temp_centigrade": 20.0, "humid_percent": 40.0},
        )
        c.post("/zone/z2/sensors", json={"temp_centigrade": 22.5})

        zones = _get_200(c, "/zones")
        assert set(zones.keys()) == {"z1", "z2"}
        assert zones["z1"]["sensors"]["temp_centigrade"] == 20.0
        assert zones["z2"]["sensors"]["temp_centigrade"] == 22.5

        _post_200(c, "/zone/z1/command", {"power": True, "mode": "HEAT", "temp_c": 21})
        _post_200(c, "/zone/z2/command", {"power": True, "mode": "COOL", "temp_c": 24})

        zones = _get_200(c, "/zones")
        assert zones["z1"]["command"]["mode"] == "HEAT"
        assert zones["z2"]["command"]["mode"] == "COOL"


def test_external_client_full_cycle(dmz_ctx: object) -> None:
    """
    Full cycle: onboard posts -> external reads -> external sets command ->
    onboard posts again and receives command.
    """
    with app.test_client() as c:
        c.post("/test_reset", json={"commands": {}, "sensors": {}})
        c.post("/zone/kitchen/sensors", json={"temp_centigrade": 19.0})

        zones = _get_200(c, "/zones")
        assert "kitchen" in zones
        _post_200(
            c,
            "/zone/kitchen/command",
            {"power": True, "mode": "HEAT", "temp_c": 20},
        )

        r = c.post(
            "/zone/kitchen/sensors",
            json={"temp_centigrade": 19.5, "humid_percent": 48.0},
        ).get_json()
        assert r["command"]["mode"] == "HEAT"
        assert r["sensors"]["temp_centigrade"] == 19.5


def test_debug_logs_returns_access_entries(dmz_ctx: object) -> None:
    """Each request is logged; GET /debug/logs returns them."""
    with app.test_client() as c:
        c.post("/test_reset", json={"commands": {}, "sensors": {}})
        c.post("/zone/z1/sensors", json={"temp_centigrade": 20.0})
        c.get("/zones")
        r = c.get("/debug/logs").get_json()
        logs = r["logs"]
        assert len(logs) >= 3
        methods = {e["method"] for e in logs}
        assert "POST" in methods
        assert "GET" in methods
        paths = [e["path"] for e in logs]
        assert "/zone/z1/sensors" in paths
        assert "/zones" in paths
        r2 = c.get("/debug/logs").get_json()
        paths2 = [e["path"] for e in r2["logs"]]
        assert "/debug/logs" in paths2
        for e in logs:
            assert "status" in e
            assert "ts" in e


def test_unsigned_request_rejected_when_auth_required(
    dmz_ctx: object, restore_zone_public_key: object
) -> None:
    """When ZONE_PUBLIC_KEY is set, POST without signature returns 401."""
    from zone_auth import generate_keypair

    _, pub_pem = generate_keypair()
    os.environ["ZONE_PUBLIC_KEY"] = pub_pem.decode()
    with app.test_client() as c:
        r = c.post(
            "/zone/z1/sensors",
            json={"temp_centigrade": 20.0},
            content_type="application/json",
        )
        assert r.status_code == 401


def test_unsigned_command_rejected_when_auth_required(
    dmz_ctx: object, restore_zone_public_key: object
) -> None:
    """When ZONE_PUBLIC_KEY is set, POST /zone/.../command without signature returns 401."""
    from zone_auth import generate_keypair

    _, pub_pem = generate_keypair()
    os.environ["ZONE_PUBLIC_KEY"] = pub_pem.decode()
    with app.test_client() as c:
        r = c.post(
            "/zone/z1/command",
            json={"power": True, "mode": "HEAT"},
            content_type="application/json",
        )
        assert r.status_code == 401


def test_unsigned_get_zones_rejected_when_auth_required(
    dmz_ctx: object, restore_zone_public_key: object
) -> None:
    """When ZONE_PUBLIC_KEY is set, GET /zones without signature returns 401 (OAuth off)."""
    from zone_auth import generate_keypair

    _, pub_pem = generate_keypair()
    os.environ["ZONE_PUBLIC_KEY"] = pub_pem.decode()
    with app.test_client() as c:
        r = c.get("/zones")
        assert r.status_code == 401


def test_signed_post_command_accepted(
    dmz_ctx: object, restore_zone_public_key: object
) -> None:
    """Valid Ed25519 signature on POST /zone/<z>/command succeeds when ZONE_PUBLIC_KEY set."""
    from zone_auth import (
        HEADER_SIGNATURE,
        HEADER_TIMESTAMP,
        HEADER_ZONE,
        generate_keypair,
        sign_request,
    )

    priv_pem, pub_pem = generate_keypair()
    os.environ["ZONE_PUBLIC_KEY"] = pub_pem.decode()
    path = "/zone/z1/command"
    body: dict = {"power": True, "mode": "HEAT", "temp_c": 21}
    body_bytes = json.dumps(body).encode()
    sig, ts, zn = sign_request("POST", path, body_bytes, "z1", priv_pem.decode())
    headers = {
        HEADER_SIGNATURE: sig,
        HEADER_TIMESTAMP: ts,
        HEADER_ZONE: zn,
        "Content-Type": "application/json",
    }
    with app.test_client() as c:
        r = c.post(path, data=body_bytes, headers=headers)
        assert r.status_code == 200, r.get_data(as_text=True)
        js = r.get_json() or {}
        assert js.get("command", {}).get("mode") == "HEAT"


def test_signed_get_zones_accepted(
    dmz_ctx: object, restore_zone_public_key: object
) -> None:
    """Valid signature on GET /zones succeeds when ZONE_PUBLIC_KEY is set."""
    from zone_auth import (
        HEADER_SIGNATURE,
        HEADER_TIMESTAMP,
        HEADER_ZONE,
        generate_keypair,
        sign_request,
    )

    priv_pem, pub_pem = generate_keypair()
    os.environ["ZONE_PUBLIC_KEY"] = pub_pem.decode()
    path = "/zones"
    body_bytes = b""
    sig, ts, zn = sign_request("GET", path, body_bytes, "z1", priv_pem.decode())
    headers = {
        HEADER_SIGNATURE: sig,
        HEADER_TIMESTAMP: ts,
        HEADER_ZONE: zn,
    }
    with app.test_client() as c:
        r = c.get(path, headers=headers)
        assert r.status_code == 200, r.get_data(as_text=True)


def test_ui_context_empty(dmz_ctx: object) -> None:
    """GET /ui/context returns empty structures when no zones exist."""
    with app.test_client() as c:
        _reset(c)
        js = _get_200(c, "/ui/context")
        assert js.get("zones") == []
        assert js.get("environments") == []
        assert js.get("zone_states") == {}


def test_ui_context_all_zones(dmz_ctx: object) -> None:
    """GET /ui/context lists every zone with state and environment rows."""
    with app.test_client() as c:
        _reset(c)
        _post_200(c, "/zone/a/command", {"power": True, "mode": "HEAT"})
        _post_200(
            c, "/zone/b/sensors", {"temp_centigrade": 14.0, "humid_percent": 40.0}
        )
        js = _get_200(c, "/ui/context")
        assert sorted(js["zones"]) == ["a", "b"]
        assert len(js["environments"]) == 2
        by_zone = {row["zone"]: row for row in js["environments"]}
        assert by_zone["b"]["temperature_centigrade"] == 14.0
        assert by_zone["b"]["humidity_percent"] == 40.0
        assert js["zone_states"]["a"]["command"]["mode"] == "HEAT"


def test_command_gate_strictly_newer_replaces(dmz_ctx: object) -> None:
    """``POST /zone/<z>/command``: only strictly-newer ``created_dt`` replaces stored command."""
    with app.test_client() as c:
        _reset(c)
        # First write: no created_dt -> DMZ stamps it.
        js0 = _post_200(c, "/zone/zg/command", {"power": True, "mode": "HEAT"})
        stamped = js0["command"].get("created_dt")
        assert isinstance(stamped, str) and stamped

        # Equal created_dt: NOT strictly newer -> ignored, stored command unchanged.
        _post_200(c, "/zone/zg/command", {"mode": "COOL", "created_dt": stamped})
        js_eq = _get_200(c, "/zones")
        assert js_eq["zg"]["command"]["mode"] == "HEAT"

        # Older created_dt: ignored.
        _post_200(
            c, "/zone/zg/command", {"mode": "AUTO", "created_dt": "1999-01-01T00:00:00"}
        )
        js_old = _get_200(c, "/zones")
        assert js_old["zg"]["command"]["mode"] == "HEAT"

        # Strictly newer: replaces.
        _post_200(
            c, "/zone/zg/command", {"mode": "COOL", "created_dt": "2099-01-01T00:00:00"}
        )
        js_new = _get_200(c, "/zones")
        assert js_new["zg"]["command"]["mode"] == "COOL"
        assert js_new["zg"]["command"]["created_dt"] == "2099-01-01T00:00:00"


def test_sensors_with_piggybacked_command_nested_body(dmz_ctx: object) -> None:
    """``POST /zone/<z>/sensors`` accepts nested ``{sensors, command}`` and gates command."""
    with app.test_client() as c:
        _reset(c)
        js = _post_200(
            c,
            "/zone/zn/sensors",
            {
                "sensors": {"temp_centigrade": 20.0, "humid_percent": 50.0},
                "command": {"mode": "HEAT", "created_dt": "2050-01-01T00:00:00"},
            },
        )
        assert js["sensors"]["temp_centigrade"] == 20.0
        assert js["command"]["mode"] == "HEAT"
        assert js["command"]["created_dt"] == "2050-01-01T00:00:00"

        # Older piggybacked command must NOT replace the stored one.
        js2 = _post_200(
            c,
            "/zone/zn/sensors",
            {
                "sensors": {"temp_centigrade": 20.5},
                "command": {"mode": "AUTO", "created_dt": "1999-01-01T00:00:00"},
            },
        )
        assert js2["sensors"]["temp_centigrade"] == 20.5
        assert js2["command"]["mode"] == "HEAT"


def test_sensors_flat_body_still_works(dmz_ctx: object) -> None:
    """Backward-compat: a flat sensors dict (no ``sensors``/``command`` keys) is accepted."""
    with app.test_client() as c:
        _reset(c)
        js = _post_200(
            c,
            "/zone/zf/sensors",
            {"temp_centigrade": 18.0, "humid_percent": 40.0},
        )
        assert js["sensors"]["temp_centigrade"] == 18.0
        assert js["sensors"]["humid_percent"] == 40.0
        assert js["command"] is None


def test_ui_command_stores_command(dmz_ctx: object) -> None:
    """POST /ui/command stores the same way as POST /zone/<z>/command."""
    with app.test_client() as c:
        _reset(c)
        r = c.post(
            "/ui/command",
            json={"zone": "z9", "command": {"power": False, "mode": "AUTO"}},
        )
        assert r.status_code == 200, r.get_data(as_text=True)
        body = r.get_json() or {}
        assert body.get("zone") == "z9"
        assert body.get("command", {}).get("mode") == "AUTO"
        zones = _get_200(c, "/zones")
        assert "z9" in zones
        assert zones["z9"]["command"]["mode"] == "AUTO"
