#!/usr/bin/env python3
"""Unit tests for HttpEmbedder against a fake loopback embeddings server.

No real runtime and no network: ``fake_http_embed`` serves the OpenAI-compatible
``/v1/embeddings`` plus Ollama's ``/api/tags`` and TEI's ``/info`` on 127.0.0.1.
"""

from __future__ import annotations

import math
import socket
import unittest

import pytest

import fake_http_embed
import fake_nlce
from fake_http_embed import FakeEmbeddingServer
from todo_embed_http import (
    PREFIX_SCHEMES,
    HttpEmbedder,
    HttpEmbedderError,
    PrefixScheme,
    get_prefix_scheme,
)


class PrefixSchemeTest(unittest.TestCase):
    """Prefix strings and their fingerprint tag; no server."""

    def test_nomic_prefixes(self) -> None:
        scheme = get_prefix_scheme("nomic")
        self.assertEqual(scheme.apply("query", "flac"), "search_query: flac")
        self.assertEqual(scheme.apply("document", "flac"), "search_document: flac")

    def test_qwen3_instructs_query_only(self) -> None:
        scheme = get_prefix_scheme("qwen3")
        self.assertTrue(scheme.apply("query", "flac").startswith("Instruct: "))
        self.assertTrue(scheme.apply("query", "flac").endswith("\nQuery:flac"))
        self.assertEqual(scheme.apply("document", "flac"), "flac")

    def test_embeddinggemma_prefixes(self) -> None:
        scheme = get_prefix_scheme("embeddinggemma")
        self.assertEqual(scheme.apply("query", "x"), "task: search result | query: x")
        self.assertEqual(scheme.apply("document", "x"), "title: none | text: x")

    def test_bge_instructs_query_only(self) -> None:
        scheme = get_prefix_scheme("bge-en-v1.5")
        self.assertEqual(
            scheme.apply("query", "x"),
            "Represent this sentence for searching relevant passages: x",
        )
        self.assertEqual(scheme.apply("document", "x"), "x")

    def test_none_is_identity(self) -> None:
        scheme = get_prefix_scheme("none")
        self.assertEqual(scheme.apply("query", "x"), "x")
        self.assertEqual(scheme.apply("document", "x"), "x")

    def test_unknown_scheme_and_role_raise(self) -> None:
        with self.assertRaises(ValueError):
            get_prefix_scheme("nope")
        with self.assertRaises(ValueError):
            get_prefix_scheme("none").apply("passage", "x")

    def test_tag_tracks_strings_not_just_name(self) -> None:
        tags = {s.tag() for s in PREFIX_SCHEMES.values()}
        self.assertEqual(len(tags), len(PREFIX_SCHEMES))
        edited = PrefixScheme("nomic", "search_query:", "search_document: ")
        self.assertNotEqual(edited.tag(), get_prefix_scheme("nomic").tag())
        self.assertTrue(edited.tag().startswith("nomic-"))

    def test_bad_constructor_args_raise(self) -> None:
        with self.assertRaises(ValueError):
            HttpEmbedder("http://127.0.0.1:1", "m", runtime="ollama", default_role="x")
        with self.assertRaises(ValueError):
            HttpEmbedder("http://127.0.0.1:1", "m", runtime="ollama", batch_size=0)
        with self.assertRaises(ValueError):
            HttpEmbedder("http://127.0.0.1:1", "m", runtime="ollama", prefix="nope")


class HttpEmbedderServerTest(unittest.TestCase):
    """Request shape, prefixes, normalization, fingerprint, failures."""

    pytestmark = pytest.mark.integration

    def _serve(self, **kwargs: object) -> FakeEmbeddingServer:
        server = FakeEmbeddingServer(**kwargs)  # type: ignore[arg-type]
        server.__enter__()
        self.addCleanup(server.__exit__, None, None, None)
        return server

    def _embedder(self, server: FakeEmbeddingServer, **kwargs: object) -> HttpEmbedder:
        kwargs.setdefault("runtime", server.runtime)
        return HttpEmbedder(server.url + "/", server.model, **kwargs)  # type: ignore[arg-type]

    def test_construct_is_lazy(self) -> None:
        server = self._serve()
        self._embedder(server)
        self.assertEqual(server.requests, [])

    def test_embed_posts_openai_shape_and_normalizes(self) -> None:
        server = self._serve()
        vec = self._embedder(server).embed("audio metadata")
        method, path, body = server.requests[0]
        self.assertEqual((method, path), ("POST", "/v1/embeddings"))
        self.assertEqual(body, {"model": fake_http_embed.MODEL, "input": ["audio metadata"]})
        self.assertEqual(len(vec), fake_http_embed.DIM)
        self.assertAlmostEqual(math.sqrt(sum(v * v for v in vec)), 1.0, places=9)
        expected = fake_nlce.bag_of_words("audio metadata", fake_http_embed.DIM)
        for got, want in zip(vec, expected):
            self.assertAlmostEqual(got, want, places=9)

    def test_query_and_document_prefixes_reach_the_wire(self) -> None:
        server = self._serve()
        emb = self._embedder(server, prefix="nomic")
        emb.embed_query("flac")
        emb.embed_document("flac")
        emb.embed("flac")
        self.assertEqual(
            server.embedding_inputs(),
            [["search_query: flac"], ["search_document: flac"], ["search_document: flac"]],
        )

    def test_default_role_query(self) -> None:
        server = self._serve()
        self._embedder(server, prefix="nomic", default_role="query").embed("flac")
        self.assertEqual(server.embedding_inputs(), [["search_query: flac"]])

    def test_batches_and_reorders_by_index(self) -> None:
        server = self._serve()
        texts = ["alpha", "beta", "gamma", "delta", "epsilon"]
        vectors = self._embedder(server, batch_size=2).embed_texts(texts)
        self.assertEqual(
            server.embedding_inputs(), [["alpha", "beta"], ["gamma", "delta"], ["epsilon"]]
        )
        for text, vec in zip(texts, vectors):
            expected = fake_nlce.bag_of_words(text, fake_http_embed.DIM)
            for got, want in zip(vec, expected):
                self.assertAlmostEqual(got, want, places=9)

    def test_ollama_fingerprint_discovers_digest(self) -> None:
        server = self._serve(runtime="ollama")
        emb = self._embedder(server, prefix="nomic")
        tag = get_prefix_scheme("nomic").tag()
        self.assertEqual(
            emb.fingerprint(),
            f"http:ollama:{fake_http_embed.MODEL}:{fake_http_embed.DIGEST}"
            f":d{fake_http_embed.DIM}:prefix={tag}:norm=l2:v1",
        )
        self.assertIn(("GET", "/api/tags", None), server.requests)
        self.assertEqual(emb.dimension(), fake_http_embed.DIM)

    def test_tei_fingerprint_discovers_model_sha(self) -> None:
        server = self._serve(runtime="tei", digest="abc123")
        fingerprint = self._embedder(server).fingerprint()
        self.assertTrue(fingerprint.startswith(f"http:tei:{fake_http_embed.MODEL}:abc123:d16:"))
        self.assertIn(("GET", "/info", None), server.requests)

    def test_explicit_digest_skips_discovery(self) -> None:
        server = self._serve(runtime="ollama")
        fingerprint = self._embedder(server, digest="sha256:pinned").fingerprint()
        self.assertIn(":sha256:pinned:", fingerprint)
        self.assertEqual([p for _, p, _ in server.requests], ["/v1/embeddings"])

    def test_fingerprint_changes_with_each_component(self) -> None:
        server = self._serve(runtime="ollama")
        base = self._embedder(server, digest="d1", prefix="none").fingerprint()
        variants = [
            self._embedder(server, digest="d2", prefix="none").fingerprint(),
            self._embedder(server, digest="d1", prefix="nomic").fingerprint(),
            self._embedder(server, digest="d1", prefix="none", runtime="tei").fingerprint(),
        ]
        for variant in variants:
            self.assertNotEqual(base, variant)
        other_dim = self._serve(runtime="ollama", dim=8)
        self.assertNotEqual(base, self._embedder(other_dim, digest="d1").fingerprint())
        other_model = self._serve(runtime="ollama", model="other-embed")
        self.assertNotEqual(base, self._embedder(other_model, digest="d1").fingerprint())

    def test_missing_digest_refuses_to_fingerprint(self) -> None:
        for runtime in ("ollama", "tei"):
            with self.subTest(runtime=runtime):
                server = self._serve(runtime=runtime, digest=None)
                with self.assertRaises(HttpEmbedderError):
                    self._embedder(server).fingerprint()
        server = self._serve()
        with self.assertRaises(HttpEmbedderError):
            self._embedder(server, runtime="vllm").fingerprint()

    def test_http_error_raises_with_status(self) -> None:
        server = self._serve(fail_status=500)
        with self.assertRaisesRegex(HttpEmbedderError, "HTTP 500"):
            self._embedder(server).embed("x")

    def test_unknown_model_raises(self) -> None:
        server = self._serve()
        emb = HttpEmbedder(server.url, "not-pulled", runtime="ollama")
        with self.assertRaisesRegex(HttpEmbedderError, "HTTP 404"):
            emb.embed("x")

    def test_dimension_change_mid_run_raises(self) -> None:
        server = self._serve(wrong_dim_after=1)
        emb = self._embedder(server)
        emb.embed("first")
        with self.assertRaisesRegex(HttpEmbedderError, "expected 16"):
            emb.embed("second")

    def test_connection_refused_raises(self) -> None:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        emb = HttpEmbedder(f"http://127.0.0.1:{port}", "m", runtime="ollama", timeout=5)
        with self.assertRaises(HttpEmbedderError):
            emb.embed("x")


if __name__ == "__main__":
    unittest.main()
