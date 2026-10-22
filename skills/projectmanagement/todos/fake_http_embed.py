"""Test support: a fake OpenAI-compatible embeddings server for ``HttpEmbedder``.

The HTTP counterpart of ``fake_nlce``: an in-process ``http.server`` bound to
127.0.0.1 on an ephemeral port, serving what Ollama and TEI serve --

* ``POST /v1/embeddings`` -- bag-of-words vectors (``fake_nlce.bag_of_words``),
  scaled by ``scale`` so tests can see the client normalize them, returned in
  reverse ``index`` order so tests can see the client reorder them;
* ``GET /api/tags`` (``runtime="ollama"``) -- one model with ``digest``;
* ``GET /info`` (``runtime="tei"``) -- ``model_id`` and ``model_sha``.

Every request is recorded in ``requests`` as ``(method, path, json_body)``.
Failure knobs: ``fail_status`` answers every request with that HTTP status;
``wrong_dim_after`` returns a vector one shorter after that many embeddings.
Nothing leaves the loopback interface.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, List, Optional, Tuple

import fake_nlce

MODEL = "fake-embed"
DIGEST = "sha256:0123456789abcdef"
DIM = 16


class FakeEmbeddingServer:
    """Context manager running the fake server; ``url`` is its base URL."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        *,
        runtime: str = "ollama",
        model: str = MODEL,
        digest: Optional[str] = DIGEST,
        dim: int = DIM,
        scale: float = 3.0,
        fail_status: Optional[int] = None,
        wrong_dim_after: Optional[int] = None,
    ) -> None:
        self.runtime = runtime
        self.model = model
        self.digest = digest
        self.dim = dim
        self.scale = scale
        self.fail_status = fail_status
        self.wrong_dim_after = wrong_dim_after
        self.requests: List[Tuple[str, str, Any]] = []
        self.embedded = 0
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        """Base URL, e.g. ``http://127.0.0.1:54321``."""
        assert self._server is not None, "server not started"
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def embedding_inputs(self) -> List[List[str]]:
        """The ``input`` list of every ``/v1/embeddings`` request, in order."""
        return [body["input"] for _, path, body in self.requests if path == "/v1/embeddings"]

    def __enter__(self) -> "FakeEmbeddingServer":
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(self))
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # -- responses -----------------------------------------------------------

    def _vector(self, text: str) -> List[float]:
        self.embedded += 1
        dim = self.dim
        if self.wrong_dim_after is not None and self.embedded > self.wrong_dim_after:
            dim -= 1
        return [self.scale * v for v in fake_nlce.bag_of_words(text, dim)]

    def respond(self, method: str, path: str, body: Any) -> Tuple[int, Any]:
        """Return ``(status, json)`` for one request."""
        self.requests.append((method, path, body))
        if self.fail_status is not None:
            return self.fail_status, {"error": "injected failure"}
        if method == "POST" and path == "/v1/embeddings":
            if not isinstance(body, dict) or body.get("model") != self.model:
                return 404, {"error": f"model {body.get('model')!r} not found"}
            inputs = body.get("input")
            if isinstance(inputs, str):
                inputs = [inputs]
            items = [
                {"object": "embedding", "index": i, "embedding": self._vector(t)}
                for i, t in enumerate(inputs)
            ]
            return 200, {"object": "list", "model": self.model, "data": items[::-1]}
        if method == "GET" and path == "/api/tags" and self.runtime == "ollama":
            entry = {"name": f"{self.model}:latest", "model": f"{self.model}:latest"}
            if self.digest is not None:
                entry["digest"] = self.digest
            return 200, {"models": [entry]}
        if method == "GET" and path == "/info" and self.runtime == "tei":
            info = {"model_id": self.model}
            if self.digest is not None:
                info["model_sha"] = self.digest
            return 200, info
        return 404, {"error": f"no route {method} {path}"}


def _handler_for(fake: FakeEmbeddingServer) -> type:
    class Handler(BaseHTTPRequestHandler):
        """Routes every request through ``fake.respond``."""

        def _reply(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            body = json.loads(raw) if raw else None
            status, payload = fake.respond(method, self.path, body)
            data = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # pylint: disable=invalid-name
            self._reply("GET")

        def do_POST(self) -> None:  # pylint: disable=invalid-name
            self._reply("POST")

        def log_message(self, *args: object) -> None:  # pylint: disable=arguments-differ
            return

    return Handler
