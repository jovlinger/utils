"""Unit tests for HttpEmbedder against an in-process fake HTTP server (no network
beyond loopback)."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from todo_embed_http import PREFIX_SCHEMES, HttpEmbedder, HttpEmbedderError

pytestmark = pytest.mark.unit

DIM = 3


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence
        pass

    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length))
        self.server.requests.append((self.path, req))
        mode = self.server.mode
        if mode == "500":
            self.send_response(500)
            self.end_headers()
            return
        if mode == "garbage":
            body = b"not json"
        elif mode == "malformed":
            body = json.dumps({"data": []}).encode()
        else:
            dim = self.server.dim
            vec = [float(len(req["input"]) + i) for i in range(dim)]
            body = json.dumps({"data": [{"embedding": vec, "index": 0}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture
def server():
    srv = HTTPServer(("127.0.0.1", 0), _Handler)
    srv.requests = []
    srv.mode = "ok"
    srv.dim = DIM
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv
    srv.shutdown()
    srv.server_close()


def test_posts_openai_shape_to_v1_embeddings(server):
    emb = HttpEmbedder(server.url + "/", "m1")
    assert emb.embed("hello") == [5.0, 6.0, 7.0]
    path, req = server.requests[0]
    assert path == "/v1/embeddings"
    assert req == {"model": "m1", "input": "hello"}


def test_nomic_prefixes_by_role(server):
    emb = HttpEmbedder(server.url, "nomic", prefix_scheme="nomic")
    emb.embed_query("q")
    emb.embed_document("d")
    emb.embed("e")
    inputs = [r["input"] for _, r in server.requests]
    assert inputs == ["search_query: q", "search_document: d", "search_document: e"]


def test_every_scheme_applies_its_own_prefixes(server):
    for name, (qp, dp) in PREFIX_SCHEMES.items():
        server.requests.clear()
        emb = HttpEmbedder(server.url, "m", prefix_scheme=name, dim=DIM)
        emb.embed_query("x")
        emb.embed_document("x")
        assert [r["input"] for _, r in server.requests] == [qp + "x", dp + "x"]


def test_explicit_prefixes_override_scheme(server):
    emb = HttpEmbedder(
        server.url, "m", prefix_scheme="custom", query_prefix="Q:", document_prefix="D:"
    )
    emb.embed_query("a")
    emb.embed_document("a")
    assert [r["input"] for _, r in server.requests] == ["Q:a", "D:a"]


def test_unknown_scheme_without_prefixes_rejected():
    with pytest.raises(HttpEmbedderError):
        HttpEmbedder("http://127.0.0.1:1", "m", prefix_scheme="nope")


def test_fingerprint_carries_all_parts(server):
    emb = HttpEmbedder(
        server.url,
        "nomic-embed-text",
        runtime="ollama",
        prefix_scheme="nomic",
        weight_digest="sha256:abc",
    )
    assert emb.fingerprint() == ("http:ollama:nomic-embed-text:sha256:abc:d3:prefix=nomic:v1")
    assert emb.dimension() == DIM


def _fp(server, **kw):
    args = dict(runtime="ollama", prefix_scheme="nomic", weight_digest="d1", dim=DIM)
    args.update(kw)
    return HttpEmbedder(
        server.url, kw.pop("model", "m"), **{k: v for k, v in args.items() if k != "model"}
    ).fingerprint()


@pytest.mark.parametrize(
    "change",
    [
        {"runtime": "tei"},
        {"model": "other"},
        {"weight_digest": "d2"},
        {"dim": 8},
        {"prefix_scheme": "none"},
        {"processing_version": "v2"},
    ],
)
def test_swapping_any_component_changes_fingerprint(server, change):
    assert _fp(server) != _fp(server, **change)


def test_dimension_probe_is_lazy_and_cached(server):
    emb = HttpEmbedder(server.url, "m")
    assert server.requests == []
    assert emb.dimension() == DIM
    assert len(server.requests) == 1
    emb.dimension()
    assert len(server.requests) == 1


def test_dim_mismatch_raises(server):
    emb = HttpEmbedder(server.url, "m", dim=5)
    with pytest.raises(HttpEmbedderError, match="expected dim 5"):
        emb.embed("x")


@pytest.mark.parametrize("mode", ["500", "garbage", "malformed"])
def test_server_errors_raise(server, mode):
    server.mode = mode
    with pytest.raises(HttpEmbedderError):
        HttpEmbedder(server.url, "m").embed("x")


def test_unreachable_raises():
    with pytest.raises(HttpEmbedderError, match="cannot reach"):
        HttpEmbedder("http://127.0.0.1:1", "m", timeout=2).embed("x")
