"""Tests for manage.py CLI helpers (DMZ_URL validation)."""

from __future__ import annotations

import contextlib
import io

import manage
import pytest


def test_zone_without_kv_prints_help_then_state_on_stdout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DMZ_URL", "http://127.0.0.1:9")
    fake_zones = {
        "z1": {
            "command": {"power": True, "mode": "HEAT", "temp_c": 22},
            "sensors": {"temp_centigrade": 20.0},
        }
    }
    monkeypatch.setattr(
        manage,
        "_request_json",
        lambda *a, **k: (200, fake_zones),
    )
    err = io.StringIO()
    out = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        code = manage._cmd_updatezone("z1", [])
    assert code == 0
    assert "updatezone <zone>" in err.getvalue()
    assert "HEAT" in out.getvalue()
    assert "temp_centigrade" in out.getvalue()


def test_zone_missing_returns_1_after_help(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMZ_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(manage, "_request_json", lambda *a, **k: (200, {}))
    err = io.StringIO()
    out = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        code = manage._cmd_updatezone("missing", [])
    assert code == 1
    assert "zone not found" in err.getvalue()
    assert out.getvalue() == ""


def test_get_zones_error_after_help_returns_1(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMZ_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(
        manage,
        "_request_json",
        lambda *a, **k: (401, {"error": "nope"}),
    )
    err = io.StringIO()
    out = io.StringIO()
    with contextlib.redirect_stderr(err), contextlib.redirect_stdout(out):
        code = manage._cmd_updatezone("z1", [])
    assert code == 1
    assert "updatezone <zone>" in err.getvalue()
    assert "nope" in err.getvalue()
    assert out.getvalue() == ""


def test_help_includes_onboard_state_example() -> None:
    msg = manage._updatezone_help_message()
    assert "updatezone <zone>" in msg
    assert '"comfort"' in msg
    assert '"half_c"' in msg
    assert '"mode"' in msg
    assert '"timer_on_minutes"' in msg
    assert "HEAT" in msg


def test_state_example_matches_to_json() -> None:
    d = manage._onboard_state_example_dict()
    assert d["mode"] == "HEAT"
    assert d["power"] is True
    assert "half_c" in d
    assert "timer_on_active" in d


def _stderr_on_dmz_base() -> tuple[int, str]:
    buf = io.StringIO()
    with contextlib.redirect_stderr(buf):
        try:
            manage._dmz_base()
        except SystemExit as exc:
            return int(exc.code or 0), buf.getvalue()
    return 0, buf.getvalue()


def test_missing_env_same_tone_as_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMZ_URL", "")
    code, err = _stderr_on_dmz_base()
    assert code == 2
    assert "DMZ_URL is not set" in err


def test_host_port_without_scheme_gets_http_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DMZ_URL", "192.168.88.200:5000")
    base = manage._dmz_base()
    assert base == "http://192.168.88.200:5000"


def test_hostname_only_without_scheme_gets_http_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DMZ_URL", "dmz.local")
    base = manage._dmz_base()
    assert base == "http://dmz.local"


def test_invalid_base_url_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMZ_URL", "///")
    code, err = _stderr_on_dmz_base()
    assert code == 2
    assert "not a valid base URL" in err


def test_accepts_http_base(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMZ_URL", "http://192.168.88.200:5000")
    base = manage._dmz_base()
    assert base == "http://192.168.88.200:5000"


def test_strips_trailing_slash(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMZ_URL", "http://dmz:5000/")
    base = manage._dmz_base()
    assert base == "http://dmz:5000"
