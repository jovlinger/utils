# Run with, from the utils repo:
# make -C render_socks5 test

from __future__ import annotations

import io
import json
import socket
import sys
import threading
import time
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "render"))
sys.path.insert(0, str(ROOT))

import render_proxy  # noqa: E402
import render_socks5_util  # noqa: E402


class _Resp:
    def __init__(self, status: int, body: bytes) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> "_Resp":
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


class FakeRender:
    def __init__(self) -> None:
        self.services: list[dict[str, Any]] = []
        self.env: dict[str, str] = {}
        self.created: list[dict[str, Any]] = []
        self.deploys: list[str] = []
        self.resumes: list[str] = []
        self.suspends: list[str] = []
        self.puts: list[str] = []
        self.roots: list[str] = []
        self.status = "live"
        self.redacted = False

    def list_owners(self) -> list[dict[str, Any]]:
        return [{"id": "own-1"}]

    def list_services(self, name: str) -> list[dict[str, Any]]:
        return [item for item in self.services if item.get("name") == name]

    def create_service(self, body: dict[str, Any], redact: str = "") -> dict[str, Any]:
        service = {
            "id": "srv-1",
            "name": body["name"],
            "suspended": "not_suspended",
            "serviceDetails": {"url": "https://tailscale-exit.onrender.com"},
        }
        self.services.append(service)
        self.created.append(body)
        self.env[render_socks5_util.AUTH_ENV] = body["envVars"][0]["value"]
        return service

    def retrieve(self, service_id: str) -> dict[str, Any]:
        return self.services[0]

    def get_env(self, service_id: str, key: str) -> str | None:
        if self.redacted:
            return ""
        return self.env.get(key)

    def put_env(self, service_id: str, key: str, value: str) -> None:
        self.puts.append(value)
        self.env[key] = value

    def deploy(self, service_id: str) -> None:
        self.deploys.append(service_id)

    def set_root_dir(self, service_id: str, root_dir: str) -> None:
        self.roots.append(root_dir)
        self.services[0]["rootDir"] = root_dir

    def latest_deploy_status(self, service_id: str) -> str:
        return self.status

    def resume(self, service_id: str) -> None:
        self.resumes.append(service_id)
        self.services[0]["suspended"] = "not_suspended"

    def suspend(self, service_id: str) -> None:
        self.suspends.append(service_id)
        self.services[0]["suspended"] = "suspended"


def _cfg(auth: str = "tskey-auth-test") -> render_socks5_util.Config:
    return render_socks5_util.Config(
        render_api_key="rnd_test",
        ts_authkey=auth,
        owner_id="own-1",
        service_name="tailscale-exit",
        repo="https://github.com/jovlinger/utils",
        branch="master",
        region="oregon",
        root_dir="render_socks5/render",
    )


def _open(_ip: str, _port: int) -> None:
    return


def _health(_url: str) -> dict[str, Any]:
    return {
        "tailscale_ip": "100.1.2.3",
        "socks_port": 1080,
        "http_port": 1055,
    }


@pytest.fixture(autouse=True)
def _isolated_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    for name in (
        "RENDER_API_KEY",
        "TS_AUTHKEY",
        "RENDER_OWNER_ID",
        "RENDER_SOCKS5_UTIL_NAME",
        "RENDER_SOCKS5_UTIL_REPO",
        "RENDER_SOCKS5_UTIL_BRANCH",
        "RENDER_SOCKS5_UTIL_REGION",
    ):
        monkeypatch.delenv(name, raising=False)


def test_missing_keys_exit_2() -> None:
    with pytest.raises(SystemExit) as caught:
        render_socks5_util.main(["up"])
    assert caught.value.code == 2


def test_up_creates_free_web_service(capsys: pytest.CaptureFixture[str]) -> None:
    api = FakeRender()
    code = render_socks5_util.cmd_up(
        _cfg(), api, poll_sleep=lambda _seconds: None, fetch=_health, probe=_open
    )
    assert code == 0
    body = api.created[0]
    assert body["serviceDetails"]["plan"] == "free"
    assert body["serviceDetails"]["runtime"] == "docker"
    assert body["serviceDetails"]["healthCheckPath"] == "/healthz"
    assert body["rootDir"] == "render_socks5/render"
    assert body["envVars"] == [{"key": "TS_AUTHKEY", "value": "tskey-auth-test"}]
    assert api.deploys == []
    out = capsys.readouterr().out
    assert "socks5: 100.1.2.3:1080" in out
    assert (
        "curl --connect-timeout 5 --socks5-hostname 100.1.2.3:1080 https://ifconfig.me"
        in out
    )


def test_up_resumes_suspended_service_without_redeploy() -> None:
    api = FakeRender()
    api.services.append(
        {
            "id": "srv-9",
            "name": "tailscale-exit",
            "suspended": "suspended",
            "serviceDetails": {"url": "https://tailscale-exit.onrender.com"},
        }
    )
    api.env["TS_AUTHKEY"] = "tskey-auth-test"
    render_socks5_util.cmd_up(
        _cfg(), api, poll_sleep=lambda _seconds: None, fetch=_health, probe=_open
    )
    assert api.created == []
    assert api.deploys == []
    assert api.puts == []
    assert api.resumes == ["srv-9"]


def test_up_rotates_auth_key() -> None:
    api = FakeRender()
    api.services.append(
        {
            "id": "srv-9",
            "name": "tailscale-exit",
            "suspended": "not_suspended",
            "serviceDetails": {"url": "https://tailscale-exit.onrender.com"},
        }
    )
    api.env["TS_AUTHKEY"] = "tskey-auth-old"
    render_socks5_util.cmd_up(
        _cfg("tskey-auth-new"),
        api,
        poll_sleep=lambda _seconds: None,
        fetch=_health,
        probe=_open,
    )
    assert api.puts == ["tskey-auth-new"]
    assert api.deploys == ["srv-9"]


def test_up_skips_redeploy_when_render_redacts_the_same_key(tmp_path: Path) -> None:
    api = FakeRender()
    api.redacted = True
    api.services.append(
        {
            "id": "srv-9",
            "name": "tailscale-exit",
            "suspended": "not_suspended",
            "serviceDetails": {"url": "https://tailscale-exit.onrender.com"},
        }
    )
    digest = render_socks5_util._sha256("tskey-auth-test")
    state = tmp_path / ".config" / "render_socks5_util"
    state.mkdir(parents=True)
    (state / "state.json").write_text(
        json.dumps({"service_id": "srv-9", "authkey_sha256": digest}),
        encoding="utf-8",
    )
    render_socks5_util.cmd_up(
        _cfg(), api, poll_sleep=lambda _seconds: None, fetch=_health, probe=_open
    )
    assert api.puts == []
    assert api.deploys == []


def test_up_rebuilds_when_socks_is_closed() -> None:
    api = FakeRender()
    api.services.append(
        {
            "id": "srv-9",
            "name": "tailscale-exit",
            "suspended": "not_suspended",
            "serviceDetails": {"url": "https://tailscale-exit.onrender.com"},
        }
    )
    api.env["TS_AUTHKEY"] = "tskey-auth-test"
    attempts = {"n": 0}

    def probe(_ip: str, _port: int) -> None:
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise OSError("cannot connect to 100.1.2.3:1080 within 5s")

    render_socks5_util.cmd_up(
        _cfg(),
        api,
        poll_sleep=lambda _seconds: None,
        fetch=_health,
        probe=probe,
    )
    assert api.deploys == ["srv-9"]


def test_up_exits_when_socks_stays_closed() -> None:
    api = FakeRender()
    api.services.append(
        {
            "id": "srv-9",
            "name": "tailscale-exit",
            "suspended": "not_suspended",
            "serviceDetails": {"url": "https://tailscale-exit.onrender.com"},
        }
    )
    api.env["TS_AUTHKEY"] = "tskey-auth-test"

    def probe(_ip: str, _port: int) -> None:
        raise OSError("cannot connect to 100.1.2.3:1080 within 5s")

    with pytest.raises(SystemExit) as caught:
        render_socks5_util.cmd_up(
            _cfg(),
            api,
            poll_sleep=lambda _seconds: None,
            fetch=_health,
            probe=probe,
        )
    assert caught.value.code == 1
    assert api.deploys == ["srv-9"]


def test_up_updates_root_dir_and_deploys() -> None:
    api = FakeRender()
    api.services.append(
        {
            "id": "srv-9",
            "name": "tailscale-exit",
            "suspended": "not_suspended",
            "rootDir": "render_exit/render",
            "serviceDetails": {"url": "https://tailscale-exit.onrender.com"},
        }
    )
    api.env["TS_AUTHKEY"] = "tskey-auth-test"
    render_socks5_util.cmd_up(
        _cfg(),
        api,
        poll_sleep=lambda _seconds: None,
        fetch=_health,
        probe=_open,
    )
    assert api.roots == ["render_socks5/render"]
    assert api.deploys == ["srv-9"]


def test_down_suspends() -> None:
    api = FakeRender()
    api.services.append(
        {
            "id": "srv-9",
            "name": "tailscale-exit",
            "suspended": "not_suspended",
            "serviceDetails": {},
        }
    )
    code = render_socks5_util.cmd_down(_cfg(), api)
    assert code == 0
    assert api.suspends == ["srv-9"]
    code = render_socks5_util.cmd_down(_cfg(), api)
    assert code == 0
    assert api.suspends == ["srv-9"]


def test_normalize_git_url() -> None:
    assert (
        render_socks5_util.normalize_git_url("git@github.com:jovlinger/utils.git")
        == "https://github.com/jovlinger/utils"
    )


def test_config_file_loads_keys(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    path = tmp_path / ".config" / "render_socks5_util" / "config.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"render_api_key": "rnd_file", "ts_authkey": "tskey-auth-file"}),
        encoding="utf-8",
    )
    path.chmod(0o644)
    monkeypatch.setenv("RENDER_SOCKS5_UTIL_REPO", "https://github.com/jovlinger/utils")
    monkeypatch.setenv("RENDER_SOCKS5_UTIL_BRANCH", "master")
    cfg = render_socks5_util.load_config()
    assert cfg.render_api_key == "rnd_file"
    assert cfg.ts_authkey == "tskey-auth-file"
    assert "chmod 600" in capsys.readouterr().err


def test_render_client_put_env_redacts_secret(
    capsys: pytest.CaptureFixture[str],
) -> None:
    def opener(req: urllib.request.Request, timeout: int = 0) -> _Resp:
        assert req.get_method() == "PUT"
        assert req.full_url.endswith("/services/srv-1/env-vars/TS_AUTHKEY")
        assert req.get_header("Authorization") == "Bearer rnd_secret"
        assert json.loads(req.data.decode()) == {"value": "tskey-auth-secret"}
        return _Resp(400, b'{"message":"bad tskey-auth-secret"}')

    api = render_socks5_util.RenderClient("rnd_secret", opener=opener)
    with pytest.raises(SystemExit):
        api.put_env("srv-1", "TS_AUTHKEY", "tskey-auth-secret")
    err = capsys.readouterr().err
    assert "tskey-auth-secret" not in err
    assert "***" in err


def test_render_client_get_env_404() -> None:
    def opener(req: urllib.request.Request, timeout: int = 0) -> _Resp:
        raise urllib.error.HTTPError(req.full_url, 404, "missing", {}, io.BytesIO(b""))

    api = render_socks5_util.RenderClient("rnd_secret", opener=opener)
    assert api.get_env("srv-1", "TS_AUTHKEY") is None


def test_parse_up_deploy_flag() -> None:
    args = render_socks5_util.parse_args(["up", "--deploy"])
    assert args.command == "up"
    assert args.deploy is True


class _Quiet(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        body = b"OK"
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: object) -> None:
        return


def test_socks_and_http_proxy_and_health() -> None:
    origin = ThreadingHTTPServer(("127.0.0.1", 0), _Quiet)
    origin_thread = threading.Thread(target=origin.serve_forever, daemon=True)
    origin_thread.start()
    servers = render_proxy.start_servers(
        host="127.0.0.1",
        http_port=0,
        socks_port=0,
        proxy_port=0,
        ip_lookup=lambda: "100.9.9.9",
    )
    threads = []
    for server in servers:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    try:
        health_port = servers[0].server_address[1]
        socks_port = servers[1].server_address[1]
        proxy_port = servers[2].server_address[1]
        origin_port = origin.server_address[1]

        with socket.create_connection(("127.0.0.1", health_port)) as health:
            health.sendall(
                b"GET /healthz HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
            )
            payload = b""
            while True:
                chunk = health.recv(4096)
                if not chunk:
                    break
                payload += chunk
        body = json.loads(payload.split(b"\r\n\r\n", 1)[1])
        assert body["tailscale_ip"] == "100.9.9.9"
        assert body["socks_port"] == socks_port

        with socket.create_connection(("127.0.0.1", socks_port)) as socks:
            socks.sendall(b"\x05\x01\x00")
            assert socks.recv(2) == b"\x05\x00"
            request = (
                b"\x05\x01\x00\x01"
                + socket.inet_aton("127.0.0.1")
                + origin_port.to_bytes(2, "big")
            )
            socks.sendall(request)
            reply = socks.recv(10)
            assert reply[1] == 0
            socks.sendall(
                b"GET / HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n"
            )
            data = b""
            while True:
                chunk = socks.recv(4096)
                if not chunk:
                    break
                data += chunk
        assert b"OK" in data

        with socket.create_connection(("127.0.0.1", proxy_port)) as proxy:
            proxy.sendall(
                f"GET http://127.0.0.1:{origin_port}/ HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: close\r\n\r\n".encode()
            )
            proxied = b""
            while True:
                chunk = proxy.recv(4096)
                if not chunk:
                    break
                proxied += chunk
        assert b"OK" in proxied
    finally:
        origin.shutdown()
        origin.server_close()
        for server in servers:
            server.shutdown()
            server.server_close()


def test_public_keepalive_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("RENDER_EXTERNAL_URL", raising=False)
    assert render_proxy.public_keepalive_url() is None
    monkeypatch.setenv("RENDER_EXTERNAL_URL", "https://example.onrender.com/")
    assert render_proxy.public_keepalive_url() == "https://example.onrender.com/healthz"


def test_keepalive_stays_quiet_when_idle() -> None:
    activity = render_proxy._ProxyActivity()
    stop = threading.Event()
    seen: list[str] = []

    def fetch(url: str) -> None:
        seen.append(url)

    thread = threading.Thread(
        target=render_proxy.run_keepalive,
        args=("https://example.test/healthz", fetch, 60, stop, activity),
        daemon=True,
    )
    thread.start()
    time.sleep(0.3)
    stop.set()
    thread.join(2)
    assert seen == []
    assert not thread.is_alive()


def test_keepalive_pings_after_a_short_connection() -> None:
    activity = render_proxy._ProxyActivity()
    stop = threading.Event()
    seen: list[str] = []

    def fetch(url: str) -> None:
        seen.append(url)
        stop.set()

    activity.enter()
    activity.leave()
    thread = threading.Thread(
        target=render_proxy.run_keepalive,
        args=("https://example.test/healthz", fetch, 60, stop, activity),
        daemon=True,
    )
    thread.start()
    thread.join(2)
    assert seen == ["https://example.test/healthz"]
    assert activity.wants_ping() is False


def test_keepalive_repeats_while_a_connection_stays_open() -> None:
    activity = render_proxy._ProxyActivity()
    stop = threading.Event()
    seen: list[str] = []

    def fetch(url: str) -> None:
        seen.append(url)
        if len(seen) >= 2:
            stop.set()

    activity.enter()
    try:
        thread = threading.Thread(
            target=render_proxy.run_keepalive,
            args=("https://example.test/healthz", fetch, 0.05, stop, activity),
            daemon=True,
        )
        thread.start()
        thread.join(2)
    finally:
        activity.leave()
    assert len(seen) >= 2


def test_socks_accept_arms_keepalive() -> None:
    previous = render_proxy._activity
    render_proxy._activity = render_proxy._ProxyActivity()
    servers = render_proxy.start_servers(
        host="127.0.0.1",
        http_port=0,
        socks_port=0,
        proxy_port=0,
        ip_lookup=lambda: None,
    )
    threads = []
    for server in servers:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    try:
        socks_port = servers[1].server_address[1]
        with socket.create_connection(("127.0.0.1", socks_port)) as socks:
            socks.sendall(b"\x05\x01\x00")
            socks.recv(2)
        deadline = time.monotonic() + 2
        while render_proxy._activity.wants_ping() is False and time.monotonic() < deadline:
            time.sleep(0.01)
        assert render_proxy._activity.wants_ping() is True
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()
        render_proxy._activity = previous
