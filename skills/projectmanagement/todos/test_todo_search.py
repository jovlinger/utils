#!/usr/bin/env python3
"""Unit tests for todo_search: tokenizing, the stemming seam, IDF, stopwords.

Unit scope, in-process. The black-box acceptance walk lives in
test_todo_search_idf.py.
"""

from __future__ import annotations

import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import todo_search  # noqa: E402


class StemTest(unittest.TestCase):
    """v1 morphology: de-pluralize, de-gerund, and nothing cleverer."""

    def test_plural_s_is_dropped(self) -> None:
        self.assertEqual(todo_search.stem("tickets"), todo_search.stem("ticket"))

    def test_double_s_is_left_alone(self) -> None:
        # "class" must not become "clas" -- the word IS its own stem.
        self.assertEqual(todo_search.stem("class"), "class")
        self.assertEqual(todo_search.stem("pass"), "pass")

    def test_es_plural_only_after_a_sibilant(self) -> None:
        # "boxes" -> "box", but "notes" keeps its e (it is a plain -s plural).
        self.assertEqual(todo_search.stem("boxes"), todo_search.stem("box"))
        self.assertEqual(todo_search.stem("notes"), todo_search.stem("note"))
        self.assertNotEqual(todo_search.stem("notes"), todo_search.stem("not"))

    def test_gerund_and_bare_verb_agree(self) -> None:
        # The case the naive substring ranker could not do: "merge" vs "merging".
        self.assertEqual(todo_search.stem("merging"), todo_search.stem("merge"))
        self.assertEqual(todo_search.stem("embeddings"), todo_search.stem("embedding"))

    def test_short_words_survive_de_gerunding(self) -> None:
        # Stripping "ing" off a short word would destroy it, so it is refused.
        for word in ("thing", "ring", "king", "string"):
            self.assertEqual(todo_search.stem(word), word)

    def test_stemming_is_idempotent(self) -> None:
        # A stem fed back in must not erode further, or the index and the query
        # would disagree depending on how many times normalization ran.
        for word in ("tickets", "merging", "class", "notes", "embeddings", "boxes"):
            once = todo_search.stem(word)
            self.assertEqual(todo_search.stem(once), once, word)


class TokenizeTest(unittest.TestCase):
    def test_splits_downcases_and_stems(self) -> None:
        self.assertEqual(
            todo_search.tokenize("Merging TICKETS, fast!"),
            [todo_search.stem("merging"), todo_search.stem("tickets"), "fast"],
        )

    def test_keeps_digits_and_alphanumerics(self) -> None:
        # Ids and ticket keys are exactly what people search for.
        self.assertEqual(todo_search.tokenize("bh 791 / ead99397"), ["bh", "791", "ead99397"])

    def test_empty_text_is_no_tokens(self) -> None:
        self.assertEqual(todo_search.tokenize(""), [])
        self.assertEqual(todo_search.tokenize("--- ... ---"), [])


class StemmerSeamTest(unittest.TestCase):
    """The hook: swapping the stemmer must not touch a single call site."""

    def test_alternate_stemmer_is_used_by_tokenize(self) -> None:
        def shouty(token: str) -> str:
            return token.upper()

        with unittest.mock.patch.object(todo_search, "STEMMER", shouty):
            self.assertEqual(todo_search.tokenize("merging tickets"), ["MERGING", "TICKETS"])
        # ...and the default is restored afterwards, so the seam is not sticky.
        self.assertEqual(todo_search.tokenize("merging"), [todo_search.stem("merging")])

    def test_default_stemmer_is_the_documented_one(self) -> None:
        self.assertIs(todo_search.STEMMER, todo_search.stem)


if __name__ == "__main__":
    unittest.main()
