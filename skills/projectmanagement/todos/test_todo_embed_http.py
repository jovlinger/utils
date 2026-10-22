#!/usr/bin/env python3
"""Unit tests for todo_embed_http.HttpEmbedder.

Hermetic: a fake transport stands in for the HTTP server, so no socket is ever
opened. The fake records each request and returns a canned (status, body).
"""

from __future__ import annotations

import json
import math
import unittest
from typing import Dict, List, Optional, Tuple

import todo_embed_http as teh


class FakeTransport:
    """Records requests; replies with a canned status/body or raises."""

    def __init__(
        self,
        vector: Optional[List[float]] = None,
        status: int = 200,
        raw: Optional[bytes] = None,
        error: Optional[BaseException] = None,
    ) -> None:
        self.vector = vector
        self.status = status
        self.raw = raw
        self.error = error
        self.calls: List[Tuple[str, bytes, Dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: Dict[str, str]) -> Tuple[int, bytes]:
        self.calls.append((url, body, headers))
        if self.error is not None:
            raise self.error
        if self.raw is not None:
            return self.status, self.raw
        payload = {"object": "list", "data": [{"index": 0, "embedding": self.vector}]}
        return self.status, json.dumps(payload).encode("utf-8")


def make(transport: FakeTransport, **overrides) -> teh.HttpEmbedder:
    kwargs = dict(
        base_url="http://fake-server:9999/",
        model="nomic-embed-text",
        dim=3,
        runtime="ollama",
        weight_digest="sha256:abc",
        query_prefix="search_query: ",
        document_prefix="search_document: ",
        transport=transport,
    )
    kwargs.update(overrides)
    return teh.HttpEmbedder(**kwargs)


class FingerprintTest(unittest.TestCase):
    """The fingerprint names runtime, model, digest, dim and prefix scheme."""

    def test_names_every_component(self) -> None:
        fp = make(FakeTransport()).fingerprint()
        self.assertIn("http:ollama:nomic-embed-text", fp)
        self.assertIn("digest=sha256:abc", fp)
        self.assertIn(":dim=3:", fp)
        self.assertIn("pfx-", fp)
        self.assertTrue(fp.endswith(":norm=l2:v1"))

    def test_each_component_change_changes_fingerprint(self) -> None:
        base = make(FakeTransport()).fingerprint()
        variants = [
            dict(runtime="tei"),
            dict(model="qwen3-embedding"),
            dict(weight_digest="sha256:def"),
            dict(dim=4),
            dict(query_prefix="query: "),
            dict(document_prefix=""),
        ]
        seen = {base}
        for override in variants:
            fp = make(FakeTransport(), **override).fingerprint()
            self.assertNotIn(fp, seen, override)
            seen.add(fp)

    def test_same_config_same_fingerprint(self) -> None:
        self.assertEqual(
            make(FakeTransport()).fingerprint(), make(FakeTransport()).fingerprint()
        )

    def test_dimension(self) -> None:
        self.assertEqual(make(FakeTransport(), dim=5).dimension(), 5)


class RequestTest(unittest.TestCase):
    """Request shape: URL, body, prefixes per side."""

    def test_posts_to_v1_embeddings_with_model_and_input(self) -> None:
        transport = FakeTransport(vector=[3.0, 0.0, 4.0])
        make(transport).embed("hello")
        url, body, headers = transport.calls[0]
        self.assertEqual(url, "http://fake-server:9999/v1/embeddings")
        self.assertEqual(json.loads(body), {"model": "nomic-embed-text", "input": "search_document: hello"})
        self.assertEqual(headers["Content-Type"], "application/json")

    def test_document_side_uses_document_prefix(self) -> None:
        transport = FakeTransport(vector=[1.0, 0.0, 0.0])
        make(transport).embed("doc text")
        self.assertEqual(json.loads(transport.calls[0][1])["input"], "search_document: doc text")

    def test_query_side_uses_query_prefix(self) -> None:
        transport = FakeTransport(vector=[1.0, 0.0, 0.0])
        make(transport).embed_query("find me")
        self.assertEqual(json.loads(transport.calls[0][1])["input"], "search_query: find me")

    def test_empty_prefix_sends_text_bare(self) -> None:
        transport = FakeTransport(vector=[1.0, 0.0, 0.0])
        make(transport, document_prefix="", query_prefix="").embed("plain")
        self.assertEqual(json.loads(transport.calls[0][1])["input"], "plain")

    def test_trailing_slash_in_base_url_is_not_doubled(self) -> None:
        transport = FakeTransport(vector=[1.0, 0.0, 0.0])
        make(transport, base_url="http://h:1").embed("x")
        self.assertEqual(transport.calls[0][0], "http://h:1/v1/embeddings")


class ResponseTest(unittest.TestCase):
    """Parsing, normalization and failure reporting."""

    def test_vector_is_l2_normalized(self) -> None:
        transport = FakeTransport(vector=[3.0, 0.0, 4.0])
        got = make(transport).embed("x")
        self.assertAlmostEqual(got[0], 0.6)
        self.assertAlmostEqual(got[1], 0.0)
        self.assertAlmostEqual(got[2], 0.8)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in got)), 1.0)

    def test_zero_vector_passes_through(self) -> None:
        transport = FakeTransport(vector=[0.0, 0.0, 0.0])
        self.assertEqual(make(transport).embed("x"), [0.0, 0.0, 0.0])

    def test_non_200_status_raises_with_status(self) -> None:
        transport = FakeTransport(status=500, raw=b"model not found")
        with self.assertRaises(RuntimeError) as ctx:
            make(transport).embed("x")
        self.assertIn("500", str(ctx.exception))
        self.assertIn("model not found", str(ctx.exception))

    def test_unreachable_server_raises_runtime_error(self) -> None:
        transport = FakeTransport(error=ConnectionRefusedError("refused"))
        with self.assertRaises(RuntimeError) as ctx:
            make(transport).embed("x")
        self.assertIn("unreachable", str(ctx.exception))

    def test_non_json_body_raises(self) -> None:
        transport = FakeTransport(raw=b"<html>bad gateway</html>")
        with self.assertRaises(RuntimeError):
            make(transport).embed("x")

    def test_missing_data_raises(self) -> None:
        transport = FakeTransport(raw=b'{"object": "list"}')
        with self.assertRaises(RuntimeError):
            make(transport).embed("x")

    def test_two_data_items_raise(self) -> None:
        body = json.dumps({"data": [{"embedding": [1, 0, 0]}, {"embedding": [0, 1, 0]}]}).encode()
        with self.assertRaises(RuntimeError):
            make(FakeTransport(raw=body)).embed("x")

    def test_non_numeric_entry_raises(self) -> None:
        body = json.dumps({"data": [{"embedding": [1, "x", 0]}]}).encode()
        with self.assertRaises(RuntimeError):
            make(FakeTransport(raw=body)).embed("x")

    def test_dimension_mismatch_raises(self) -> None:
        transport = FakeTransport(vector=[1.0, 0.0])
        with self.assertRaises(RuntimeError) as ctx:
            make(transport, dim=3).embed("x")
        self.assertIn("dimension", str(ctx.exception))

    def test_nonpositive_dim_rejected_at_construction(self) -> None:
        with self.assertRaises(ValueError):
            make(FakeTransport(), dim=0)


if __name__ == "__main__":
    unittest.main()
