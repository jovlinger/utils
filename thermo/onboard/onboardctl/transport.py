"""HTTP transport to onboard debug ports (no DMZ)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Protocol, Sequence

from zonespec import BoardTarget


class Transport(Protocol):
    def get_json(self, target: BoardTarget, path: str) -> Any:
        ...

    def post_json(
        self, target: BoardTarget, path: str, body: Mapping[str, Any]
    ) -> Any:
        ...


@dataclass
class HttpTransport:
    timeout_s: float = 15.0

    def _url(self, target: BoardTarget, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return target.base_url.rstrip("/") + path

    def get_json(self, target: BoardTarget, path: str) -> Any:
        req = urllib.request.Request(self._url(target, path), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} GET {path}: {body}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"GET {path} failed for {target.base_url}: {exc}") from exc

    def post_json(
        self, target: BoardTarget, path: str, body: Mapping[str, Any]
    ) -> Any:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self._url(target, path),
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            body_text = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {exc.code} POST {path}: {body_text}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"POST {path} failed for {target.base_url}: {exc}") from exc


@dataclass
class FakeTransport:
    """In-memory transport for unit tests."""

    get_responses: Dict[str, Any] = field(default_factory=dict)
    get_errors: Dict[str, BaseException] = field(default_factory=dict)
    post_log: List[Dict[str, Any]] = field(default_factory=list)
    default_get: Any = field(default_factory=dict)

    def get_json(self, target: BoardTarget, path: str) -> Any:
        key = f"{target.zone_name}:{path}"
        if key in self.get_errors:
            raise self.get_errors[key]
        if path in self.get_errors:
            raise self.get_errors[path]
        if key in self.get_responses:
            return self.get_responses[key]
        if path in self.get_responses:
            return self.get_responses[path]
        return self.default_get

    def post_json(
        self, target: BoardTarget, path: str, body: Mapping[str, Any]
    ) -> Any:
        entry = {"zone": target.zone_name, "path": path, "body": dict(body)}
        self.post_log.append(entry)
        return {"ok": True, "echo": entry}


class AmbiguousTargetsError(ValueError):
    """Mutating command refused because zonespec matched multiple boards."""


def require_single_target(
    targets: Sequence[BoardTarget],
    *,
    mutating: bool,
    spec_text: str,
) -> BoardTarget:
    if not targets:
        raise ValueError(f"no boards match zonespec {spec_text!r}")
    if len(targets) > 1:
        names = ", ".join(t.zone_name for t in targets)
        if mutating:
            raise AmbiguousTargetsError(
                f"zonespec {spec_text!r} matches multiple boards ({names}); "
                "narrow the selector before a mutating command"
            )
        # read-only: caller may iterate; still expose helper for single-need
    return targets[0]
