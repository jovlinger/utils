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


class HashEmbedderRemovedTest(unittest.TestCase):
    """The lexical bag-of-words `hash` embedder is gone, class and registry key both."""

    def test_class_is_gone(self) -> None:
        self.assertFalse(hasattr(todo_embed, "HashEmbedder"))

    def test_key_is_unselectable(self) -> None:
        with self.assertRaises(ValueError):
            todo_embed.get_embedder("hash")


class RegistryTest(unittest.TestCase):
    """Embedder registry and cosine helper."""

    def test_default_set_is_non_hidden(self) -> None:
        names = todo_embed.default_embedder_names()
        self.assertEqual(names, ["apple"])
        # available_embedders mirrors the default (non-hidden) set.
        self.assertEqual(todo_embed.available_embedders(), names)

    def test_hidden_excluded_but_selectable(self) -> None:
        # mock/null/st are hidden: not in the default set...
        self.assertNotIn("mock", todo_embed.default_embedder_names())
        self.assertNotIn("null", todo_embed.default_embedder_names())
        self.assertNotIn("st", todo_embed.default_embedder_names())
        # ...but still selectable by exact key.
        self.assertEqual(todo_embed.get_embedder("mock").fingerprint(), "mock")

    def test_no_cheap_embedders(self) -> None:
        # `hash` used to hold the cheap slot; nothing eagerly embeds on write
        # until a cheap SEMANTIC backend replaces it. Callers must tolerate [].
        self.assertEqual(todo_embed.cheap_embedders(), [])

    def test_cheap_plumbing_still_works_when_a_backend_registers(self) -> None:
        # The `cheap` mechanism is retained for that successor, so keep it covered
        # even while no shipped backend sets the flag.
        todo_embed.register_embedder("cheap-probe", todo_embed.MockEmbedder, cheap=True)
        try:
            self.assertEqual(
                [e.fingerprint() for e in todo_embed.cheap_embedders()], ["mock"]
            )
        finally:
            del todo_embed._BACKENDS["cheap-probe"]
        self.assertEqual(todo_embed.cheap_embedders(), [])

    def test_list_embedders_flags(self) -> None:
        flags = dict((key, (cheap, hidden)) for key, cheap, hidden in todo_embed.list_embedders())
        self.assertNotIn("hash", flags)
        self.assertEqual(flags["apple"], (False, False))
        self.assertEqual(flags["st"], (False, True))

    def test_unknown_embedder_raises(self) -> None:
        with self.assertRaises(ValueError):
            todo_embed.get_embedder("no-such-embedder")

    def test_cosine_identical(self) -> None:
        vec: List[float] = [1.0, 0.0, 0.0]
        self.assertAlmostEqual(todo_embed.cosine_similarity(vec, vec), 1.0)


if __name__ == "__main__":
    unittest.main()
