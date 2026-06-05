"""Tests for manage.py CLI helpers (DMZ_URL validation)."""

from __future__ import annotations

import contextlib
import io
import subprocess
import sys
from pathlib import Path
from typing import Optional

import manage
import pytest


def _find_utils_root() -> Optional[Path]:
    for parent in Path(__file__).resolve().parents:
        if (parent / "lib" / "venv-resolve.sh").is_file():
            return parent
    return None


UTILS_ROOT = _find_utils_root()
VENV_RESOLVE = UTILS_ROOT / "lib" / "venv-resolve.sh" if UTILS_ROOT else None


def _make_fake_venv(base: Path, name: str = ".venv") -> Path:
    venv = base / name
    bin_dir = venv / "bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "activate").write_text("# fake activate\n", encoding="utf-8")
    (bin_dir / "python").symlink_to(sys.executable)
    return venv


def _resolve_venv(start: Path, utils_root: Path) -> subprocess.CompletedProcess[str]:
    assert VENV_RESOLVE is not None
    script = (
        '. "$1"; '
        'resolve_utils_venv "$2" "$3"; '
        'printf "%s\\n" "$VENV_DIR"; '
        'utils_venv_python_bin "$VENV_DIR"'
    )
    return subprocess.run(
        ["/bin/sh", "-c", script, "sh", str(VENV_RESOLVE), str(start), str(utils_root)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_venv_resolver_walks_up_to_nearest_complete_venv(tmp_path: Path) -> None:
    if VENV_RESOLVE is None:
        pytest.skip("utils venv resolver is not present in this layout")
    project = tmp_path / "project"
    deep = project / "a" / "b"
    deep.mkdir(parents=True)
    expected = _make_fake_venv(project)

    res = _resolve_venv(deep, tmp_path)

    assert res.returncode == 0, res.stderr
    assert res.stdout.splitlines()[0] == str(expected)


def test_venv_resolver_stops_at_empty_marker(tmp_path: Path) -> None:
    if VENV_RESOLVE is None:
        pytest.skip("utils venv resolver is not present in this layout")
    project = tmp_path / "project"
    deep = project / "sub" / "tool"
    deep.mkdir(parents=True)
    _make_fake_venv(project)
    marker = project / "sub" / ".venv"
    marker.mkdir()
    (marker / "README.md").write_text("# marker\n", encoding="utf-8")

    res = _resolve_venv(deep, tmp_path)

    assert res.returncode == 1
    assert "No usable venv" in res.stderr
    assert str(marker) in res.stderr


def test_manage_launcher_uses_venv_run() -> None:
    dmz_dir = Path(__file__).resolve().parent.parent
    launcher = dmz_dir / "manage"
    manage_py = dmz_dir / "manage.py"
    assert launcher.is_symlink()
    assert launcher.resolve() == manage_py.resolve()
    shebang = manage_py.read_text(encoding="utf-8").splitlines()[0]
    assert "venv-run" in shebang


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


def test_raw_ir_parser_accepts_signed_integer_text() -> None:
    payload = manage._parse_raw_ir_text("4500 -4500, 560 -1600\n560 -520\n")

    assert payload == {
        "command_type": "raw_ir_sequence",
        "sequence": [4500, -4500, 560, -1600, 560, -520],
        "carrier_hz": 38000,
    }


def test_raw_ir_parser_accepts_json_object() -> None:
    payload = manage._parse_raw_ir_text(
        '{"sequence":[9000,-4500,560,-560],"carrier_hz":38000}'
    )

    assert payload["command_type"] == "raw_ir_sequence"
    assert payload["sequence"] == [9000, -4500, 560, -560]
    assert payload["carrier_hz"] == 38000


def test_raw_ir_parser_rejects_zero_duration() -> None:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        with pytest.raises(SystemExit) as ei:
            manage._parse_raw_ir_text("[4500, 0, -560]")

    assert ei.value.code == 2
    assert "must not be zero" in err.getvalue()


def test_rawir_posts_typed_command_from_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw_file = tmp_path / "capture.txt"
    raw_file.write_text("4500 -4500 560 -1600\n", encoding="utf-8")
    calls: list[tuple] = []

    def _fake_request_json(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return 200, {"ok": True}

    monkeypatch.setattr(manage, "_request_json", _fake_request_json)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = manage.main(["rawir", "office", str(raw_file)])

    assert code == 0
    assert len(calls) == 1
    method, path, kwargs = calls[0]
    assert method == "POST"
    assert path == "/zone/office/command"
    assert kwargs["zone_for_sign"] == "office"
    assert kwargs["sign"] is True
    assert kwargs["body"] == {
        "command_type": "raw_ir_sequence",
        "sequence": [4500, -4500, 560, -1600],
        "carrier_hz": 38000,
    }
    assert '"ok": true' in out.getvalue()


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


def test_no_args_prints_usage_exit_0() -> None:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        code = manage.main([])
    assert code == 0
    assert "healthz" in err.getvalue()
    assert "DMZ_URL=http://your-host:5000 manage healthz" in err.getvalue()
    assert "manage help" in err.getvalue()


def test_help_action_prints_full_doc() -> None:
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = manage.main(["help"])
    assert code == 0
    text = out.getvalue()
    assert "CLI for the DMZ HTTP API" in text
    assert "healthz" in text
    assert "DMZ_URL=http://your-host:5000 manage healthz" in text


def test_dash_help_is_unknown_action() -> None:
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        with pytest.raises(SystemExit) as ei:
            manage.main(["--help"])
    assert ei.value.code == 2
    assert "unknown action" in err.getvalue()


def test_healthz_calls_ui_diagnostics_unsigned(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMZ_URL", "http://127.0.0.1:9")
    calls: list[tuple] = []

    def _fake_request_json(method, path, **kwargs):
        calls.append((method, path, kwargs))
        return 200, {"uptime_seconds": 1.0, "config": {"oauth_enabled": False}}

    monkeypatch.setattr(manage, "_request_json", _fake_request_json)
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = manage.main(["healthz"])
    assert code == 0
    assert len(calls) == 1
    method, path, kwargs = calls[0]
    assert method == "GET"
    assert path == "/ui/diagnostics"
    assert kwargs["sign"] is False
    assert "uptime_seconds" in out.getvalue()


@pytest.mark.parametrize(
    ("exc", "needle"),
    [
        (
            manage.requests.exceptions.ConnectionError(
                "HTTPConnectionPool(host='127.0.0.1', port=9): Max retries exceeded "
                "(Caused by NewConnectionError: [Errno 61] Connection refused))"
            ),
            "connection refused",
        ),
        (
            manage.requests.exceptions.ConnectionError(
                "HTTPConnectionPool(host='no-such-host.invalid', port=5000): Max retries exceeded "
                "(Caused by NameResolutionError: Failed to resolve 'no-such-host.invalid')"
            ),
            "host not found",
        ),
    ],
)
def test_connection_errors_are_succinct(
    monkeypatch: pytest.MonkeyPatch,
    exc: BaseException,
    needle: str,
) -> None:
    monkeypatch.setenv("DMZ_URL", "http://127.0.0.1:9")

    def _boom(*_a, **_k):
        raise exc

    monkeypatch.setattr(manage.requests, "get", _boom)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        with pytest.raises(SystemExit) as ei:
            manage.main(["healthz"])
    assert ei.value.code == 1
    text = err.getvalue()
    assert needle in text.lower()
    assert "traceback" not in text.lower()
    assert text.count("\n") <= 2


def test_oauth_redirect_to_login_is_succinct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DMZ_URL", "http://jovlinger.duckdns.org:5000")

    class _Resp:
        status_code = 302
        headers = {"Location": "/login"}
        content = b""
        text = ""

    monkeypatch.setattr(manage, "_http_request", lambda *a, **k: _Resp())
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        with pytest.raises(SystemExit) as ei:
            manage.main(["zones"])
    assert ei.value.code == 1
    text = err.getvalue()
    assert "OAuth redirect" in text
    assert "/login" in text
    assert "ZONE_PRIVATE_KEY" in text
    assert "traceback" not in text.lower()
    assert text.count("\n") <= 2


def test_zones_signs_with_default_zone_when_zone_name_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ZONE_NAME", raising=False)
    monkeypatch.setenv("DMZ_URL", "http://127.0.0.1:9")
    calls: list[str] = []

    def _fake_request_json(method, path, **kwargs):
        calls.append(kwargs.get("zone_for_sign", ""))
        return 200, {}

    monkeypatch.setattr(manage, "_request_json", _fake_request_json)
    code = manage.main(["zones"])
    assert code == 0
    assert calls == ["cli"]


def test_missing_cryptography_shows_venv_local_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ZONE_PRIVATE_KEY_PATH", "/fake/priv.pem")

    def _boom(*_a, **_k):
        raise RuntimeError("cryptography not installed; pip install cryptography")

    import zone_auth

    monkeypatch.setattr(zone_auth, "sign_request", _boom)
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        with pytest.raises(SystemExit) as ei:
            manage._sign_headers("GET", "/zones", b"", "cli")
    assert ei.value.code == 1
    text = err.getvalue()
    assert sys.executable in text
    assert "bin/.venv" in text
    assert "thermo/dmz" in text or ".venv" in text
    assert "not a system-wide" in text or "not bin/.venv" in text
