#!/usr/bin/env python3
"""Unit tests for todo_embed embedder implementations."""

from __future__ import annotations

import math
import os
import unittest
import unittest.mock
from typing import List

import todo_embed


class EmbedderAbcTest(unittest.TestCase):
    """Embedder ABC cannot be instantiated directly."""

    def test_abc_not_instantiable(self) -> None:
        with self.assertRaises(TypeError):
            todo_embed.Embedder()  # type: ignore[abstract]


class NullEmbedderTest(unittest.TestCase):
    """NullEmbedder returns zero vectors."""

    def test_name_and_dimension(self) -> None:
        embedder = todo_embed.NullEmbedder(dim=4)
        self.assertEqual(embedder.fingerprint(), "null")
        self.assertEqual(embedder.dimension(), 4)

    def test_embed_is_zeros(self) -> None:
        embedder = todo_embed.NullEmbedder(dim=4)
        self.assertEqual(embedder.embed("anything"), [0.0, 0.0, 0.0, 0.0])


class MockEmbedderTest(unittest.TestCase):
    """MockEmbedder is deterministic and normalized."""

    def test_name(self) -> None:
        self.assertEqual(todo_embed.MockEmbedder().fingerprint(), "mock")

    def test_deterministic(self) -> None:
        embedder = todo_embed.MockEmbedder(dim=8)
        first = embedder.embed("hello")
        second = embedder.embed("hello")
        self.assertEqual(first, second)

    def test_normalized(self) -> None:
        vec = todo_embed.MockEmbedder(dim=8).embed("hello")
        norm = math.sqrt(sum(v * v for v in vec))
        self.assertAlmostEqual(norm, 1.0, places=5)


class HashEmbedderTest(unittest.TestCase):
    """HashEmbedder is the default local embedder."""

    def test_name_and_default_dim(self) -> None:
        embedder = todo_embed.HashEmbedder()
        self.assertEqual(embedder.fingerprint(), "hash")
        self.assertEqual(embedder.dimension(), 128)

    def test_shared_tokens_increase_similarity(self) -> None:
        embedder = todo_embed.HashEmbedder()
        a = embedder.embed("vector search test")
        b = embedder.embed("vector search example")
        c = embedder.embed("unrelated gibberish")
        sim_ab = todo_embed.cosine_similarity(a, b)
        sim_ac = todo_embed.cosine_similarity(a, c)
        self.assertGreater(sim_ab, sim_ac)

    def test_get_embedder_default_is_hash(self) -> None:
        env = os.environ.copy()
        env.pop("TODO_EMBEDDER", None)
        with unittest.mock.patch.dict(os.environ, env, clear=False):
            embedder = todo_embed.get_embedder()
        self.assertEqual(embedder.fingerprint(), "hash")


class RegistryTest(unittest.TestCase):
    """Embedder registry and cosine helper."""

    def test_available_embedders(self) -> None:
        names = todo_embed.available_embedders()
        self.assertIn("hash", names)
        self.assertIn("mock", names)
        self.assertIn("null", names)

    def test_unknown_embedder_raises(self) -> None:
        with self.assertRaises(ValueError):
            todo_embed.get_embedder("no-such-embedder")

    def test_cosine_identical(self) -> None:
        vec: List[float] = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(todo_embed.cosine_similarity(vec, vec), 1.0)


if __name__ == "__main__":
    unittest.main()
