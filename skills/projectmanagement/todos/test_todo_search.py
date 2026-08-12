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


class IdfTest(unittest.TestCase):
    def test_rarer_term_weighs_more(self) -> None:
        # 10 documents: a term in one of them must outweigh one in nine.
        rare = todo_search.inverse_document_frequency(10, 1)
        common = todo_search.inverse_document_frequency(10, 9)
        self.assertGreater(rare, common)

    def test_universal_term_weighs_nothing(self) -> None:
        self.assertEqual(todo_search.inverse_document_frequency(10, 10), 0.0)

    def test_empty_corpus_is_not_a_division_by_zero(self) -> None:
        self.assertEqual(todo_search.inverse_document_frequency(0, 0), 0.0)

    def test_document_frequency_counts_documents_not_occurrences(self) -> None:
        frequencies = todo_search.document_frequencies(
            [["a", "a", "a", "b"], ["a"], ["c"]]
        )
        self.assertEqual(frequencies, {"a": 2, "b": 1, "c": 1})


class LexicalIndexTest(unittest.TestCase):
    """The ranker itself: what it ranks first, and what it refuses to return."""

    def _index(self, **texts: str) -> todo_search.LexicalIndex:
        return todo_search.LexicalIndex(texts)

    def test_rare_match_outranks_common_match(self) -> None:
        # This is the whole point of the change. Both documents match exactly
        # one query term; the one matching the RARE term must win.
        texts = {"rare": "quokka sighting", "common": "widget inventory"}
        texts.update({f"filler{n}": "widget maintenance" for n in range(8)})
        scores = todo_search.LexicalIndex(texts).score(["widget", "quokka"])
        self.assertGreater(scores["rare"], scores["common"])

    def test_documents_matching_nothing_are_absent(self) -> None:
        scores = self._index(a="alpha", b="beta", g="gamma").score(["alpha", "beta"])
        self.assertEqual({"a", "b"}, set(scores))

    def test_contiguous_phrase_outranks_scattered_words(self) -> None:
        # A quoted phrase is one term; IDF alone cannot tell these apart, since
        # both documents hold both tokens.
        scores = self._index(
            phrase="alpha beta", split="beta gamma alpha"
        ).score(["alpha beta"])
        self.assertGreater(scores["phrase"], scores["split"])

    def test_term_in_every_document_still_returns_them(self) -> None:
        # Smoothed IDF is exactly 0 for a universal term; without a floor these
        # documents would score 0 and vanish from their own search.
        scores = self._index(a="widget one", b="widget two").score(["widget"])
        self.assertEqual({"a", "b"}, set(scores))

    def test_stopwords_are_skipped_when_the_query_has_other_terms(self) -> None:
        index = todo_search.LexicalIndex(
            {"a": "the quokka", "b": "the widget"}, stopwords=["the"]
        )
        scores = index.score(["the", "quokka"])
        self.assertIn("a", scores)
        self.assertNotIn("b", scores, "a stopword-only match should not surface")

    def test_an_all_stopword_query_still_finds_its_documents(self) -> None:
        # Refusing to answer would be worse than answering with weak signal.
        index = todo_search.LexicalIndex({"a": "the widget"}, stopwords=["the"])
        self.assertIn("a", index.score(["the"]))

    def test_stopwords_are_matched_after_stemming(self) -> None:
        # The list is stored as words; the index holds stems.
        index = todo_search.LexicalIndex(
            {"a": "tickets and quokka", "b": "tickets and widget"}, stopwords=["ticket"]
        )
        self.assertNotIn("b", index.score(["tickets", "quokka"]))

    def test_query_matches_across_morphology(self) -> None:
        scores = self._index(m="merging the branch", o="unrelated").score(["merge"])
        self.assertEqual({"m"}, set(scores))

    def test_empty_query_and_empty_corpus_are_empty_results(self) -> None:
        self.assertEqual({}, self._index(a="alpha").score([]))
        self.assertEqual({}, todo_search.LexicalIndex({}).score(["alpha"]))

    def test_discovers_the_corpus_wide_term_as_a_stopword(self) -> None:
        texts = {f"d{n}": "widget work" for n in range(9)}
        texts["rare"] = "quokka work"
        index = todo_search.LexicalIndex(texts)
        discovered = index.stopword_candidates(0.3)
        self.assertIn("widget", discovered)
        self.assertIn("work", discovered)
        self.assertNotIn("quokka", discovered)


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
