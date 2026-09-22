"""Apple NLContextualEmbedding backend via a long-lived Swift sidecar.

macOS-only. The heavy work -- loading the on-device model and mean-pooling its
token vectors -- happens in a native sidecar binary (``apple_embedder/nlce-embed``)
that we talk to over JSON lines. The sidecar is started lazily on the first embed
and then kept alive: embedding is rare next to other todo operations, but the
model load (and any first-run asset download) is expensive, so we pay it once.

Protocol -- one JSON object per line, both directions::

    ->  {"op": "info"}                  <-  {"model": str, "revision": int, "dim": int}
    ->  {"op": "embed", "text": "..."}  <-  {"vector": [float, ...]}
    (any request)                       <-  {"error": "..."}   on failure

The fingerprint faithfully records whatever model the sidecar loaded (its
identifier and Apple's own integer revision) plus this code's pooling version, so
vectors are only ever compared within the exact space that produced them.
"""

from __future__ import annotations

import atexit
import json
import os
import platform
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from todo_embed import Embedder

_ENV_BIN = "TODO_APPLE_NLCE_BIN"
_DEFAULT_BIN = Path(__file__).resolve().parent / "apple_embedder" / "nlce-embed"
_MIN_MACOS: Tuple[int, int] = (14, 0)
# Bump when the sidecar's pooling/normalization changes: it is part of the
# fingerprint, so old vectors are never compared against reprocessed ones.
_PROCESSING_VERSION = "v1"


class AppleEmbedderError(RuntimeError):
    """Apple embedder backend failure."""


def _macos_version() -> Tuple[int, int]:
    parts = platform.mac_ver()[0].split(".")
    if not parts or not parts[0]:
        return (0, 0)
    try:
        major = int(parts[0])
        minor = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return (0, 0)
    return (major, minor)


class AppleEmbedder(Embedder):
    """Embed text with Apple's on-device NLContextualEmbedding via a sidecar."""

    def __init__(
        self,
        bin_path: Optional[str] = None,
        *,
        processing_version: str = _PROCESSING_VERSION,
    ) -> None:
        explicit = bin_path is not None or bool(os.environ.get(_ENV_BIN))
        self._bin = bin_path or os.environ.get(_ENV_BIN) or str(_DEFAULT_BIN)
        # A caller-supplied binary is trusted as-is (tests point at a fake; a dev
        # may point at a custom build), so only the default native path is gated.
        if not explicit:
            if platform.system() != "Darwin":
                raise AppleEmbedderError("Apple embedder requires macOS")
            if _macos_version() < _MIN_MACOS:
                raise AppleEmbedderError(
                    f"Apple embedder requires macOS {_MIN_MACOS[0]}+ "
                    f"(have {platform.mac_ver()[0] or 'unknown'})"
                )
        if not Path(self._bin).exists():
            raise AppleEmbedderError(
                f"sidecar binary not found at {self._bin}; run `make apple-embedder`"
            )
        self._processing_version = processing_version
        self._proc: Optional[subprocess.Popen] = None
        self._model: Optional[str] = None
        self._revision: Optional[int] = None
        self._dim: Optional[int] = None
        self._fingerprint: Optional[str] = None
        atexit.register(self.close)

    # -- lifecycle ---------------------------------------------------------

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def _start(self) -> None:
        try:
            self._proc = subprocess.Popen(
                [self._bin],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
                bufsize=1,
            )
        except OSError as exc:
            raise AppleEmbedderError(f"failed to start sidecar {self._bin}: {exc}") from exc
        info = self._raw_request({"op": "info"})
        try:
            self._model = str(info["model"])
            self._revision = int(info["revision"])
            self._dim = int(info["dim"])
        except (KeyError, TypeError, ValueError) as exc:
            self.close()
            raise AppleEmbedderError(f"sidecar sent malformed info: {info!r}") from exc
        self._fingerprint = (
            f"apple_nlce:{self._model}:r{self._revision}"
            f":pool=mean:norm=l2:{self._processing_version}"
        )

    def _ensure_started(self) -> None:
        if not self._alive():
            self._start()

    def close(self) -> None:
        """Terminate the sidecar if it is running (idempotent)."""
        proc = self._proc
        self._proc = None
        if proc is None or proc.poll() is not None:
            return
        try:
            if proc.stdin is not None:
                proc.stdin.close()
            proc.terminate()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()

    # -- io ----------------------------------------------------------------

    def _raw_request(self, obj: Dict[str, Any]) -> Dict[str, Any]:
        proc = self._proc
        if proc is None or proc.stdin is None or proc.stdout is None:
            raise AppleEmbedderError("sidecar not running")
        try:
            proc.stdin.write(json.dumps(obj) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError) as exc:
            raise AppleEmbedderError("sidecar stdin closed") from exc
        line = proc.stdout.readline()
        if line == "":
            raise AppleEmbedderError("sidecar exited without a response")
        try:
            reply = json.loads(line)
        except json.JSONDecodeError as exc:
            raise AppleEmbedderError(f"sidecar sent non-JSON: {line!r}") from exc
        if not isinstance(reply, dict):
            raise AppleEmbedderError(f"sidecar sent non-object: {reply!r}")
        if "error" in reply:
            raise AppleEmbedderError(f"sidecar error: {reply['error']}")
        return reply

    def _request(self, obj: Dict[str, Any]) -> Dict[str, Any]:
        """Send a request, restarting the sidecar once if it has died."""
        self._ensure_started()
        try:
            return self._raw_request(obj)
        except AppleEmbedderError:
            # One respawn: a long-lived sidecar may have been reaped between calls.
            self.close()
            self._start()
            return self._raw_request(obj)

    # -- Embedder ----------------------------------------------------------

    def fingerprint(self) -> str:
        self._ensure_started()
        assert self._fingerprint is not None
        return self._fingerprint

    def dimension(self) -> int:
        self._ensure_started()
        assert self._dim is not None
        return self._dim

    def embed(self, text: str) -> List[float]:
        reply = self._request({"op": "embed", "text": text})
        vector = reply.get("vector")
        if not isinstance(vector, list):
            raise AppleEmbedderError(f"sidecar embed reply missing vector: {reply!r}")
        return [float(x) for x in vector]
