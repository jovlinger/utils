#!/usr/bin/env python3
"""Bring a userspace Tailscale egress proxy up or down on Render's free tier.

Render free containers have no /dev/net/tun and no root netfilter, so this
is not a kernel exit node. ``up`` deploys ``render_socks5/render`` as a free web
service. tailscaled runs with userspace networking
(``--tun=userspace-networking``). Tailscale Serve
publishes a SOCKS5 proxy on port 1080 and an HTTP proxy on port 1055 at the
node's 100.x address. Clients on the tailnet connect there; the container
dials the public internet, so the far side sees Render's address.

    render_socks5_util up
    render_socks5_util down

``down`` suspends the service. An ephemeral node then drops off the tailnet.
A free instance also sleeps after 15 minutes without an HTTP request to its
public URL. ``up`` wakes it, checks that the SOCKS port accepts a connection,
and starts a new build when it does not. Pass nothing. A failure exits
non-zero.

Keys live in the environment or in ~/.config/render_socks5_util/config.json
(mode 0600). Environment variables win.

    RENDER_API_KEY   render_api_key
    TS_AUTHKEY       ts_authkey

TS_AUTHKEY is either an OAuth client secret (tskey-client-...) or an
ephemeral reusable auth key. Both must carry tag:render. A one-time auth
key cannot log in again after Render sleeps. See ``render_socks5_util --help``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

API_ROOT = "https://api.render.com/v1"
SERVICE_NAME = "tailscale-exit"
ROOT_DIR = "render_socks5/render"
AUTH_ENV = "TS_AUTHKEY"
REPO_ROOT = Path(__file__).resolve().parents[1]

Opener = Callable[..., Any]
SleepFn = Callable[[float], None]

_HELP = """\
keys
  RENDER_API_KEY   render_api_key   dashboard.render.com account settings, API keys
  TS_AUTHKEY       ts_authkey       Tailscale OAuth client secret or auth key

  Optional: RENDER_OWNER_ID (owner_id), RENDER_SOCKS5_UTIL_NAME (service_name),
  RENDER_SOCKS5_UTIL_REGION (region), RENDER_SOCKS5_UTIL_REPO (repo),
  RENDER_SOCKS5_UTIL_BRANCH (branch).

Tailscale tag
  In Access controls, tag:render must be owned by you. If the tailnet is
  still allow-all, that is the only policy edit. Otherwise also grant your
  devices ports 1080 and 1055 on tag:render.

      "tagOwners": { "tag:render": ["autogroup:admin"] }

  OAuth client (preferred): scope auth_keys, tag tag:render. Put the client
  secret in TS_AUTHKEY. OAuth nodes are ephemeral, and the secret still
  works after a cold start.

  Auth key: ephemeral, reusable, tag tag:render. Reusable is required
  because each wake logs in again. A one-time key dies on the first
  suspend or 15-minute sleep. The key itself expires within 90 days.

Render builds the git repo and branch in the config (default origin of
this checkout, https://github.com/jovlinger/utils, directory
render_socks5/render), not the unpushed working tree.
"""


def _die(message: str, code: int = 1) -> None:
    print(f"render_socks5_util: {message}", file=sys.stderr)
    raise SystemExit(code)


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize_git_url(url: str) -> str:
    if url.startswith("git@github.com:"):
        url = "https://github.com/" + url[len("git@github.com:") :]
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url


def _origin_https(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "remote", "get-url", "origin"],
        capture_output=True,
        text=True,
        check=False,
    )
    return normalize_git_url(proc.stdout.strip())


def _current_branch(root: Path) -> str:
    proc = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    branch = proc.stdout.strip()
    if not branch or branch == "HEAD":
        return "master"
    return branch


def unpushed_warning(root: Path, branch: str) -> Optional[str]:
    """Return a warning when Render would build something other than HEAD."""
    head = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    remote = subprocess.run(
        ["git", "-C", str(root), "rev-parse", f"origin/{branch}"],
        capture_output=True,
        text=True,
        check=False,
    )
    dirty = subprocess.run(
        [
            "git",
            "-C",
            str(root),
            "status",
            "--porcelain",
            "--",
            "render_socks5",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    messages = []
    if head.returncode == 0 and remote.returncode == 0:
        if head.stdout.strip() != remote.stdout.strip():
            messages.append(
                f"origin/{branch} does not match HEAD; Render builds the pushed branch"
            )
    if dirty.stdout.strip():
        messages.append("uncommitted changes under render_socks5/ are not deployed")
    if not messages:
        return None
    return "render_socks5_util: " + "; ".join(messages)


class Config:
    def __init__(
        self,
        render_api_key: str,
        ts_authkey: str,
        owner_id: str,
        service_name: str,
        repo: str,
        branch: str,
        region: str,
        root_dir: str,
    ) -> None:
        self.render_api_key = render_api_key
        self.ts_authkey = ts_authkey
        self.owner_id = owner_id
        self.service_name = service_name
        self.repo = repo
        self.branch = branch
        self.region = region
        self.root_dir = root_dir


def _config_dir() -> Path:
    return Path.home() / ".config" / "render_socks5_util"


def _config_path() -> Path:
    return _config_dir() / "config.json"


def _state_path() -> Path:
    return _config_dir() / "state.json"


def _file_config() -> dict[str, Any]:
    path = _config_path()
    if not path.exists():
        return {}
    mode = path.stat().st_mode
    if mode & 0o077:
        print(
            f"render_socks5_util: {path} is readable by others; chmod 600",
            file=sys.stderr,
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        _die(f"{path} must be a JSON object")
    return data


def _pick(
    env_name: str, file_data: Mapping[str, Any], file_key: str, default: str
) -> str:
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value
    file_value = file_data.get(file_key)
    if isinstance(file_value, str) and file_value:
        return file_value
    return default


def load_config(root: Path = REPO_ROOT) -> Config:
    file_data = _file_config()
    repo = _pick("RENDER_SOCKS5_UTIL_REPO", file_data, "repo", "")
    if not repo:
        repo = _origin_https(root)
    branch = _pick("RENDER_SOCKS5_UTIL_BRANCH", file_data, "branch", "")
    if not branch:
        branch = _current_branch(root)
    return Config(
        render_api_key=_pick("RENDER_API_KEY", file_data, "render_api_key", ""),
        ts_authkey=_pick("TS_AUTHKEY", file_data, "ts_authkey", ""),
        owner_id=_pick("RENDER_OWNER_ID", file_data, "owner_id", ""),
        service_name=_pick(
            "RENDER_SOCKS5_UTIL_NAME", file_data, "service_name", SERVICE_NAME
        ),
        repo=repo,
        branch=branch,
        region=_pick("RENDER_SOCKS5_UTIL_REGION", file_data, "region", "oregon"),
        root_dir=_pick("RENDER_SOCKS5_UTIL_ROOT", file_data, "root_dir", ROOT_DIR),
    )


def _load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if isinstance(data, dict):
        return data
    return {}


def _save_state(service_id: str, auth_hash: str) -> None:
    directory = _config_dir()
    directory.mkdir(parents=True, exist_ok=True)
    path = _state_path()
    payload = json.dumps({"service_id": service_id, "authkey_sha256": auth_hash})
    path.write_text(payload + "\n", encoding="utf-8")
    os.chmod(path, 0o600)


def _response_status(resp: Any) -> int:
    status_value = getattr(resp, "status", None)
    if status_value is None:
        status_value = resp.getcode()
    return int(status_value)


class RenderClient:
    def __init__(self, api_key: str, opener: Optional[Opener] = None) -> None:
        self.api_key = api_key
        self._opener = opener or urllib.request.urlopen

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[object] = None,
        ok: Sequence[int] = (200, 201, 202, 204),
        redact: str = "",
    ) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            API_ROOT + path,
            data=data,
            method=method,
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
        )
        try:
            resp = self._opener(req, timeout=60)
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
        else:
            with resp:
                status = _response_status(resp)
                raw = resp.read()
        if status not in ok:
            text = raw.decode("utf-8", "replace")[:500]
            for secret in (self.api_key, redact):
                if secret:
                    text = text.replace(secret, "***")
            _die(f"Render {method} {path} returned {status}: {text}")
        if not raw:
            return status, None
        return status, json.loads(raw.decode("utf-8"))

    def list_owners(self) -> list[dict[str, Any]]:
        _status, payload = self._request("GET", "/owners")
        return _unwrap(payload, "owner")

    def list_services(self, name: str) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"name": name, "limit": "20"})
        _status, payload = self._request("GET", "/services?" + query)
        return _unwrap(payload, "service")

    def create_service(self, body: dict[str, Any], redact: str = "") -> dict[str, Any]:
        _status, payload = self._request(
            "POST", "/services", body, ok=(200, 201, 202), redact=redact
        )
        return _as_service(payload)

    def retrieve(self, service_id: str) -> dict[str, Any]:
        _status, payload = self._request("GET", f"/services/{service_id}")
        return _as_service(payload)

    def get_env(self, service_id: str, key: str) -> Optional[str]:
        quoted = urllib.parse.quote(key, safe="")
        path = f"/services/{service_id}/env-vars/{quoted}"
        data = None
        req = urllib.request.Request(
            API_ROOT + path,
            data=data,
            method="GET",
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Accept": "application/json",
            },
        )
        try:
            resp = self._opener(req, timeout=60)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            text = exc.read().decode("utf-8", "replace")[:500]
            _die(f"Render GET {path} returned {exc.code}: {text}")
        else:
            with resp:
                status = _response_status(resp)
                raw = resp.read()
        if status == 404:
            return None
        if status != 200:
            _die(f"Render GET {path} returned {status}")
        payload = json.loads(raw.decode("utf-8"))
        if isinstance(payload, dict) and isinstance(payload.get("envVar"), dict):
            payload = payload["envVar"]
        if isinstance(payload, dict):
            value = payload.get("value")
            if isinstance(value, str):
                return value
        return None

    def put_env(self, service_id: str, key: str, value: str) -> None:
        quoted = urllib.parse.quote(key, safe="")
        self._request(
            "PUT",
            f"/services/{service_id}/env-vars/{quoted}",
            {"value": value},
            redact=value,
        )

    def deploy(self, service_id: str) -> None:
        self._request(
            "POST",
            f"/services/{service_id}/deploys",
            {"clearCache": "do_not_clear"},
            ok=(200, 201, 202),
        )

    def set_root_dir(self, service_id: str, root_dir: str) -> None:
        self._request(
            "PATCH",
            f"/services/{service_id}",
            {"rootDir": root_dir},
            ok=(200, 202),
        )

    def latest_deploy_status(self, service_id: str) -> str:
        _status, payload = self._request(
            "GET", f"/services/{service_id}/deploys?limit=1"
        )
        if not isinstance(payload, list) or not payload:
            return ""
        item = payload[0]
        if isinstance(item, dict) and isinstance(item.get("deploy"), dict):
            item = item["deploy"]
        if isinstance(item, dict) and isinstance(item.get("status"), str):
            return item["status"]
        return ""

    def resume(self, service_id: str) -> None:
        self._request("POST", f"/services/{service_id}/resume", ok=(200, 202))

    def suspend(self, service_id: str) -> None:
        self._request("POST", f"/services/{service_id}/suspend", ok=(200, 202))


def _unwrap(payload: Any, inner: str) -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        _die("Render returned an unexpected list")
    found: list[dict[str, Any]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        nested = item.get(inner)
        if isinstance(nested, dict):
            found.append(nested)
        else:
            found.append(item)
    return found


def _as_service(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        _die("Render returned an unexpected service")
    nested = payload.get("service")
    if isinstance(nested, dict):
        return nested
    return payload


def service_root_dir(service: Mapping[str, Any]) -> str:
    root = service.get("rootDir")
    if isinstance(root, str) and root:
        return root
    details = service.get("serviceDetails")
    if isinstance(details, dict):
        nested = details.get("rootDir")
        if isinstance(nested, str) and nested:
            return nested
    return ""


def service_url(service: Mapping[str, Any]) -> str:
    details = service.get("serviceDetails")
    if isinstance(details, dict):
        url = details.get("url")
        if isinstance(url, str):
            return url
    return ""


def create_body(cfg: Config, owner_id: str) -> dict[str, Any]:
    return {
        "type": "web_service",
        "name": cfg.service_name,
        "ownerId": owner_id,
        "repo": cfg.repo,
        "autoDeploy": "no",
        "branch": cfg.branch,
        "rootDir": cfg.root_dir,
        "envVars": [{"key": AUTH_ENV, "value": cfg.ts_authkey}],
        "serviceDetails": {
            "runtime": "docker",
            "plan": "free",
            "region": cfg.region,
            "healthCheckPath": "/healthz",
            "envSpecificDetails": {
                "dockerfilePath": "./Dockerfile",
                "dockerContext": ".",
            },
        },
    }


def _owner_id(cfg: Config, api: RenderClient) -> str:
    if cfg.owner_id:
        return cfg.owner_id
    owners = api.list_owners()
    if len(owners) != 1:
        _die("set RENDER_OWNER_ID; this API key can see more than one workspace")
    owner_id = owners[0].get("id")
    if not isinstance(owner_id, str) or not owner_id:
        _die("Render owner id was missing")
    return owner_id


def _find_service(cfg: Config, api: RenderClient) -> Optional[dict[str, Any]]:
    matches = [
        service
        for service in api.list_services(cfg.service_name)
        if service.get("name") == cfg.service_name
    ]
    if len(matches) > 1:
        _die(f"more than one Render service is named {cfg.service_name}")
    if not matches:
        return None
    return matches[0]


_FAILED_DEPLOYS = {
    "build_failed",
    "update_failed",
    "pre_deploy_failed",
    "canceled",
    "deactivated",
}


def _wait_live(
    api: RenderClient,
    service_id: str,
    timeout: float,
    poll_sleep: SleepFn,
) -> None:
    deadline = time.monotonic() + timeout
    last = ""
    while True:
        last = api.latest_deploy_status(service_id)
        if last == "live":
            return
        if last in _FAILED_DEPLOYS:
            _die(f"deploy {last}")
        if time.monotonic() >= deadline:
            _die(f"deploy did not go live (last status {last or 'unknown'})")
        poll_sleep(5)


def _wait_health(
    url: str,
    timeout: float,
    poll_sleep: SleepFn,
    fetch_health: Callable[[str], Mapping[str, Any]],
) -> Mapping[str, Any]:
    deadline = time.monotonic() + timeout
    last = "no response"
    while True:
        try:
            body = fetch_health(url)
        except Exception as exc:  # noqa: BLE001 - health retries any wake failure
            last = str(exc)
        else:
            ip = body.get("tailscale_ip")
            if isinstance(ip, str) and ip:
                return body
            last = "tailscale address not ready"
        if time.monotonic() >= deadline:
            _die(f"service did not publish a tailnet address ({last})")
        poll_sleep(5)


def probe_socks(ip: str, port: int, timeout: float = 5) -> None:
    """Raise if this machine cannot open TCP to the proxy within timeout."""
    try:
        with socket.create_connection((ip, int(port)), timeout=timeout):
            return
    except OSError as exc:
        raise OSError(
            f"cannot connect to {ip}:{port} within {timeout:.0f}s ({exc})"
        ) from exc


def fetch_health(url: str) -> dict[str, Any]:
    req = urllib.request.Request(
        url.rstrip("/") + "/healthz",
        headers={"Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("healthz was not a JSON object")
    return payload


def _key_changed(previous: Optional[str], authkey: str, previous_hash: str) -> bool:
    if previous == authkey:
        return False
    if previous in (None, "") and previous_hash == _sha256(authkey):
        return False
    return True


def _proxy_ports(health: Mapping[str, Any]) -> tuple[str, int, int]:
    ip = health["tailscale_ip"]
    if not isinstance(ip, str) or not ip:
        _die("service did not publish a tailnet address")
    socks_port = health.get("socks_port", 1080)
    http_port = health.get("http_port", 1055)
    return ip, int(socks_port), int(http_port)


def _print_ready(url: str, ip: str, socks_port: int, http_port: int) -> None:
    print(f"service: {url}")
    print(f"socks5: {ip}:{socks_port}")
    print(f"http: {ip}:{http_port}")
    print(
        f"curl --connect-timeout 5 --socks5-hostname {ip}:{socks_port} "
        "https://ifconfig.me"
    )


def cmd_up(
    cfg: Config,
    api: RenderClient,
    *,
    deploy: bool = False,
    poll_sleep: SleepFn = time.sleep,
    fetch: Callable[[str], Mapping[str, Any]] = fetch_health,
    probe: Callable[[str, int], None] = probe_socks,
    deploy_timeout: float = 900,
    health_timeout: float = 180,
) -> int:
    if not cfg.render_api_key or not cfg.ts_authkey:
        _die("set RENDER_API_KEY and TS_AUTHKEY", 2)
    if not cfg.repo:
        _die("set RENDER_SOCKS5_UTIL_REPO to the GitHub repo Render should build")
    owner_id = _owner_id(cfg, api)
    service = _find_service(cfg, api)
    created = service is None
    if service is None:
        service = api.create_service(create_body(cfg, owner_id), redact=cfg.ts_authkey)
    service_id = service.get("id")
    if not isinstance(service_id, str) or not service_id:
        _die("Render did not return a service id")
    state = _load_state()
    previous_hash = state.get("authkey_sha256")
    if not isinstance(previous_hash, str):
        previous_hash = ""
    need_deploy = deploy
    if not created:
        current_root = service_root_dir(service) or service_root_dir(
            api.retrieve(service_id)
        )
        if current_root and current_root != cfg.root_dir:
            api.set_root_dir(service_id, cfg.root_dir)
            need_deploy = True
        previous = api.get_env(service_id, AUTH_ENV)
        if _key_changed(previous, cfg.ts_authkey, previous_hash):
            api.put_env(service_id, AUTH_ENV, cfg.ts_authkey)
            need_deploy = True
        _save_state(service_id, _sha256(cfg.ts_authkey))
    if need_deploy and not created:
        api.deploy(service_id)
    if service.get("suspended") == "suspended":
        api.resume(service_id)
    if created or need_deploy:
        _wait_live(api, service_id, deploy_timeout, poll_sleep)
    url = service_url(service)
    if not url:
        url = service_url(api.retrieve(service_id))
    if not url:
        _die("Render did not return a service URL")
    health = _wait_health(url, health_timeout, poll_sleep, fetch)
    ip, socks_port, http_port = _proxy_ports(health)
    try:
        probe(ip, socks_port)
    except OSError as exc:
        if created or need_deploy:
            _die(f"{exc}. Run render_socks5_util up")
        api.deploy(service_id)
        if service.get("suspended") == "suspended":
            api.resume(service_id)
        _wait_live(api, service_id, deploy_timeout, poll_sleep)
        fresh = service_url(api.retrieve(service_id))
        if fresh:
            url = fresh
        health = _wait_health(url, health_timeout, poll_sleep, fetch)
        ip, socks_port, http_port = _proxy_ports(health)
        try:
            probe(ip, socks_port)
        except OSError as again:
            _die(f"{again}. Run render_socks5_util up")
    _print_ready(url, ip, socks_port, http_port)
    return 0


def cmd_down(cfg: Config, api: RenderClient) -> int:
    if not cfg.render_api_key:
        _die("set RENDER_API_KEY", 2)
    service = _find_service(cfg, api)
    if service is None:
        _die(f"no Render service named {cfg.service_name}")
    service_id = service.get("id")
    name = service.get("name", cfg.service_name)
    if not isinstance(service_id, str):
        _die("Render did not return a service id")
    if service.get("suspended") == "suspended":
        print(f"already suspended {name} ({service_id})")
        return 0
    api.suspend(service_id)
    print(f"suspended {name} ({service_id})")
    return 0


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="render_socks5_util",
        description=(
            "Deploy or suspend a userspace Tailscale SOCKS5/HTTP egress "
            "proxy on a Render free web service."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=_HELP,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    up = sub.add_parser(
        "up", help="create or wake the proxy and print its tailnet address"
    )
    up.add_argument(
        "--deploy",
        action="store_true",
        help="rebuild even when the SOCKS port is already accepting connections",
    )
    sub.add_parser(
        "down", help="suspend the service so the ephemeral node leaves the tailnet"
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def main(
    argv: Optional[Sequence[str]] = None, client: Optional[RenderClient] = None
) -> int:
    args = parse_args(argv)
    cfg = load_config()
    if args.command == "up":
        warning = unpushed_warning(REPO_ROOT, cfg.branch)
        if warning:
            print(warning, file=sys.stderr)
    api = client or RenderClient(cfg.render_api_key)
    if args.command == "up":
        return cmd_up(cfg, api, deploy=bool(args.deploy))
    return cmd_down(cfg, api)


if __name__ == "__main__":
    raise SystemExit(main())
