#!/usr/bin/env python3
"""Unit tests for HttpEmbedder against a fake in-process /v1/embeddings server.

No network beyond loopback: a stdlib HTTPServer on 127.0.0.1 records requests
and replies with deterministic vectors.
"""

from __future__ import annotations

import hashlib
import json
import math
import struct
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, List

from todo_embed_http import PREFIX_SCHEMES, HttpEmbedder, HttpEmbedderError
import pytest

DIM = 4


def _vec(text: str) -> List[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [float(x) + 1.0 for x in struct.unpack("<4h", digest[:8])]


class _Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802
        server: Any = self.server
        length = int(self.headers.get("Content-Length", "0"))
        req = json.loads(self.rfile.read(length))
        server.requests.append((self.path, req))
        mode = server.mode
        if mode == "http500":
            self._send(500, b"boom")
            return
        if mode == "malformed":
            self._send(200, b'{"nope": 1}')
            return
        if mode == "baddim":
            self._send(200, json.dumps({"data": [{"embedding": [1.0, 2.0]}]}).encode())
            return
        data = [{"index": i, "embedding": _vec(t)} for i, t in enumerate(req["input"])]
        self._send(200, json.dumps({"data": data}).encode())

    def _send(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: Any) -> None:
        pass


class _FakeServer:
    def __enter__(self) -> "_FakeServer":
        self.httpd: Any = HTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.requests = []
        self.httpd.mode = "ok"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"
        return self

    def __exit__(self, *exc: Any) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join()

    @property
    def requests(self) -> list:
        return self.httpd.requests

    def set_mode(self, mode: str) -> None:
        self.httpd.mode = mode


@pytest.mark.unit
class HttpEmbedderTest(unittest.TestCase):
    def test_embed_posts_openai_shape_and_normalizes(self) -> None:
        with _FakeServer() as srv:
            emb = HttpEmbedder(srv.url, "m1")
            vec = emb.embed("hello")
            path, body = srv.requests[0]
        self.assertEqual(path, "/v1/embeddings")
        self.assertEqual(body, {"model": "m1", "input": ["hello"]})
        self.assertEqual(len(vec), DIM)
        self.assertAlmostEqual(math.sqrt(sum(x * x for x in vec)), 1.0)

    def test_document_and_query_use_their_own_prefixes(self) -> None:
        with _FakeServer() as srv:
            emb = HttpEmbedder(srv.url, "nomic", prefix_scheme="nomic")
            doc = emb.embed("cats")
            query = emb.embed_query("cats")
            sent = [b["input"][0] for _, b in srv.requests]
        self.assertEqual(sent, ["search_document: cats", "search_query: cats"])
        self.assertNotEqual(doc, query)

    def test_each_scheme_applies_its_declared_prefixes(self) -> None:
        for name, (qp, dp) in PREFIX_SCHEMES.items():
            with self.subTest(scheme=name), _FakeServer() as srv:
                emb = HttpEmbedder(srv.url, "m", prefix_scheme=name)
                emb.embed("x")
                emb.embed_query("x")
                sent = [b["input"][0] for _, b in srv.requests]
            self.assertEqual(sent, [dp + "x", qp + "x"])

    def test_bge_has_no_document_prefix(self) -> None:
        self.assertEqual(PREFIX_SCHEMES["bge"][1], "")
        self.assertEqual(PREFIX_SCHEMES["qwen3"][1], "")
        self.assertTrue(PREFIX_SCHEMES["qwen3"][0].startswith("Instruct: "))

    def test_dimension_is_probed_once(self) -> None:
        with _FakeServer() as srv:
            emb = HttpEmbedder(srv.url, "m")
            self.assertEqual(emb.dimension(), DIM)
            self.assertEqual(emb.dimension(), DIM)
            self.assertEqual(len(srv.requests), 1)

    def test_fingerprint_names_runtime_model_digest_dim_scheme(self) -> None:
        with _FakeServer() as srv:
            fp = HttpEmbedder(
                srv.url,
                "nomic-embed-text",
                runtime="ollama",
                digest="abc123",
                prefix_scheme="nomic",
            ).fingerprint()
        self.assertTrue(
            fp.startswith("http:ollama:nomic-embed-text:abc123:d4:nomic:"), fp
        )

    def test_fingerprint_changes_when_any_component_changes(self) -> None:
        base = dict(runtime="ollama", digest="d1", prefix_scheme="nomic")
        with _FakeServer() as srv:
            fps = {
                "base": HttpEmbedder(srv.url, "m", **base).fingerprint(),
                "runtime": HttpEmbedder(
                    srv.url, "m", **{**base, "runtime": "tei"}
                ).fingerprint(),
                "model": HttpEmbedder(srv.url, "m2", **base).fingerprint(),
                "digest": HttpEmbedder(
                    srv.url, "m", **{**base, "digest": "d2"}
                ).fingerprint(),
                "scheme": HttpEmbedder(
                    srv.url, "m", **{**base, "prefix_scheme": "bge"}
                ).fingerprint(),
            }
            fixed = HttpEmbedder(srv.url, "m", dim=DIM, **base).fingerprint()
        self.assertEqual(len(set(fps.values())), len(fps))
        self.assertEqual(fixed, fps["base"])

    def test_fingerprint_changes_with_prefix_text(self) -> None:
        with _FakeServer() as srv:
            a = HttpEmbedder(srv.url, "m", prefix_scheme="nomic").fingerprint()
            PREFIX_SCHEMES["nomic-x"] = ("q: ", "d: ")
            try:
                b = HttpEmbedder(srv.url, "m", prefix_scheme="nomic-x").fingerprint()
            finally:
                del PREFIX_SCHEMES["nomic-x"]
        self.assertNotEqual(a.rsplit(":", 1)[1], b.rsplit(":", 1)[1])

    def test_unknown_scheme_rejected(self) -> None:
        with self.assertRaises(HttpEmbedderError):
            HttpEmbedder("http://127.0.0.1:1", "m", prefix_scheme="bogus")

    def test_http_error_raises(self) -> None:
        with _FakeServer() as srv:
            srv.set_mode("http500")
            with self.assertRaisesRegex(HttpEmbedderError, "HTTP 500"):
                HttpEmbedder(srv.url, "m").embed("x")

    def test_malformed_response_raises(self) -> None:
        with _FakeServer() as srv:
            srv.set_mode("malformed")
            with self.assertRaisesRegex(HttpEmbedderError, "malformed"):
                HttpEmbedder(srv.url, "m").embed("x")

    def test_dimension_mismatch_raises(self) -> None:
        with _FakeServer() as srv:
            srv.set_mode("baddim")
            with self.assertRaisesRegex(HttpEmbedderError, "dim 2"):
                HttpEmbedder(srv.url, "m", dim=DIM).embed("x")

    def test_connection_refused_raises(self) -> None:
        with _FakeServer() as srv:
            url = srv.url
        with self.assertRaises(HttpEmbedderError):
            HttpEmbedder(url, "m", timeout=2).embed("x")


if __name__ == "__main__":
    unittest.main()
