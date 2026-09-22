#!/usr/bin/env python3
"""Unit tests for todo_search: tokenizing, the stemming seam, IDF, stopwords.

Unit scope, in-process. The black-box acceptance walk lives in
test_todo_search_idf.py.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import unittest
import unittest.mock
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import todo  # noqa: E402  (direct import: unit coverage for _solo_term_id_prefix_hit)
import todo_search  # noqa: E402
from test_todo import TodoCase  # noqa: E402  (temp-repo + subprocess harness)


class ParseSearchQueryTest(unittest.TestCase):
    """Colon-based time operators are stripped; text terms pass through."""

    def test_strips_time_operators_and_keeps_text(self) -> None:
        terms, filters = todo.parse_search_query(
            [
                "alpha",
                "tc_after:2026-01-01T00:00:00Z",
                "tc_before:2026-12-31T23:59:59Z",
                "beta",
            ]
        )
        self.assertEqual(terms, ["alpha", "beta"])
        self.assertEqual(filters.create_after, "2026-01-01T00:00:00Z")
        self.assertEqual(filters.create_before, "2026-12-31T23:59:59Z")

    def test_update_operators(self) -> None:
        _terms, filters = todo.parse_search_query(
            [
                "tu_after:2026-06-01T12:00:00Z",
                "tu_before:2026-06-30T12:00:00Z",
            ]
        )
        self.assertEqual(filters.update_after, "2026-06-01T12:00:00Z")
        self.assertEqual(filters.update_before, "2026-06-30T12:00:00Z")

    def test_unknown_colon_token_is_a_text_term(self) -> None:
        terms, _filters = todo.parse_search_query(["foo:bar"])
        self.assertEqual(terms, ["foo:bar"])

    def test_date_only_expands_to_day_bounds(self) -> None:
        _terms, filters = todo.parse_search_query(
            [
                "tc_after:2026-08-25",
                "tc_before:2026-08-31",
            ]
        )
        self.assertEqual(filters.create_after, "2026-08-25T00:00:00Z")
        self.assertEqual(filters.create_before, "2026-08-31T23:59:59Z")

    def test_slash_dates_normalize_to_hyphens(self) -> None:
        _terms, filters = todo.parse_search_query(["tc_after:2026/08/26"])
        self.assertEqual(filters.create_after, "2026-08-26T00:00:00Z")

    def test_invalid_timestamp_errors(self) -> None:
        with self.assertRaises(todo.TodoError):
            todo.parse_search_query(["tc_after:not-a-date"])

    def test_empty_operator_value_errors(self) -> None:
        with self.assertRaises(todo.TodoError):
            todo.parse_search_query(["tc_after:"])


class SearchTimeFilterTest(TodoCase):
    """Time operators AND with text search and filter create/update_dt."""

    def test_tc_after_date_only_filters_by_create_dt(self) -> None:
        old_id = self.mint()
        new_id = self.mint()
        self.write_ticket(
            f"{old_id[:8]}-o",
            old_id,
            summary="old widget",
            extra={"create_dt": "2026-08-24T12:00:00Z", "update_dt": "2026-08-24T12:00:00Z"},
        )
        self.write_ticket(
            f"{new_id[:8]}-n",
            new_id,
            summary="new widget",
            extra={"create_dt": "2026-08-25T12:00:00Z", "update_dt": "2026-08-25T12:00:00Z"},
        )
        proc = self.todo(
            "search",
            "tc_after:2026-08-25",
            "widget",
            "--embedder",
            "apple",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(new_id[:8], proc.stdout)
        self.assertNotIn(old_id[:8], proc.stdout)

    def test_tc_after_filters_by_create_dt(self) -> None:
        old_id = self.mint()
        new_id = self.mint()
        self.write_ticket(
            f"{old_id[:8]}-o",
            old_id,
            summary="old widget",
            extra={"create_dt": "2026-01-01T00:00:00Z", "update_dt": "2026-01-01T00:00:00Z"},
        )
        self.write_ticket(
            f"{new_id[:8]}-n",
            new_id,
            summary="new widget",
            extra={"create_dt": "2026-06-01T00:00:00Z", "update_dt": "2026-06-01T00:00:00Z"},
        )
        proc = self.todo(
            "search",
            "tc_after:2026-03-01T00:00:00Z",
            "widget",
            "--embedder",
            "apple",
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(new_id[:8], proc.stdout)
        self.assertNotIn(old_id[:8], proc.stdout)

    def test_operator_only_lists_matching_todos(self) -> None:
        in_id = self.mint()
        out_id = self.mint()
        self.write_ticket(
            f"{in_id[:8]}-i",
            in_id,
            summary="inside",
            extra={"create_dt": "2026-06-01T00:00:00Z", "update_dt": "2026-06-01T00:00:00Z"},
        )
        self.write_ticket(
            f"{out_id[:8]}-o",
            out_id,
            summary="outside",
            extra={"create_dt": "2026-01-01T00:00:00Z", "update_dt": "2026-01-01T00:00:00Z"},
        )
        proc = self.todo("search", "tc_after:2026-03-01T00:00:00Z", "--embedder", "apple")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(in_id[:8], proc.stdout)
        self.assertNotIn(out_id[:8], proc.stdout)

    def test_hidden_by_status_reported_on_stderr(self) -> None:
        done_id = self.mint()
        self.write_ticket(
            f"{done_id[:8]}-d",
            done_id,
            summary="done ticket",
            extra={
                "create_dt": "2026-08-30T00:00:00Z",
                "update_dt": "2026-08-30T00:00:00Z",
                "State": {"done": {}},
            },
        )
        proc = self.todo("search", "tc_after:2026-08-26", "--embedder", "apple")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(proc.stdout.strip(), "")
        self.assertIn("... 1 hidden by status", proc.stderr)


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


class EmbedderOffSwitchTest(TodoCase):
    """`"embedder": null` in config.json: lexical IDF only, nothing instantiated."""

    def _set_config(self, **keys) -> None:
        config = json.loads((self._db_dir / "config.json").read_text(encoding="utf-8"))
        config.update(keys)
        (self._db_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")

    def _embedding_count(self) -> int:
        db = self._db_dir / "sqlite.db"
        if not db.exists():
            return 0
        conn = sqlite3.connect(str(db))
        try:
            return conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        finally:
            conn.close()

    def _seed(self) -> str:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-q", tid, summary="quokka sighting log")
        return tid[:8]

    def test_off_switch_searches_without_any_embedder(self) -> None:
        # Point the sidecar at a path that does not exist: anything trying to
        # embed would fail loudly, so success proves nothing tried.
        short = self._seed()
        self._set_config(embedder=None)
        self._env["TODO_APPLE_NLCE_BIN"] = str(self._db_dir / "nope")
        proc = self.todo("search", "quokka")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(short, proc.stdout)
        self.assertEqual(0, self._embedding_count(), "off switch still wrote vectors")

    def test_explicit_embedder_flag_overrides_the_off_switch(self) -> None:
        short = self._seed()
        self._set_config(embedder=None)
        proc = self.todo("search", "quokka", "--embedder", "apple")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(short, proc.stdout)
        self.assertGreater(self._embedding_count(), 0, "--embedder should still embed")

    def test_a_named_embedder_in_config_is_used(self) -> None:
        self._seed()
        self._set_config(embedder="apple")
        proc = self.todo("search", "quokka")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreater(self._embedding_count(), 0)

    def test_absent_key_disables_embedders(self) -> None:
        self._seed()
        proc = self.todo("search", "quokka")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(0, self._embedding_count(), "default is lexical-only")

    def test_a_nonsense_value_is_an_error_not_a_silent_default(self) -> None:
        self._seed()
        self._set_config(embedder=17)
        proc = self.todo("search", "quokka")
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("embedder", proc.stderr)


class SoloTermIdPrefixHitTest(unittest.TestCase):
    """Unit coverage for the helper search_tickets consults for a solo term."""

    IDS = {"cafefeed" + "0" * 56: {}, "deadbeef" + "0" * 56: {}}

    def test_unique_prefix_match_is_returned(self) -> None:
        hit = todo._solo_term_id_prefix_hit(["cafefeed"], self.IDS)
        self.assertEqual("cafefeed" + "0" * 56, hit)

    def test_full_id_also_matches(self) -> None:
        full = "cafefeed" + "0" * 56
        self.assertEqual(full, todo._solo_term_id_prefix_hit([full], self.IDS))

    def test_no_match_returns_none(self) -> None:
        self.assertIsNone(todo._solo_term_id_prefix_hit(["ffffffff"], self.IDS))

    def test_ambiguous_match_returns_none(self) -> None:
        ids = {"aaaa1111" + "0" * 56: {}, "aaaa2222" + "0" * 56: {}}
        self.assertIsNone(todo._solo_term_id_prefix_hit(["aaaa"], ids))

    def test_multiple_terms_never_engage_the_prefix_path(self) -> None:
        # A second term would otherwise win uniquely -- proving it is the term
        # COUNT, not the match, that disqualifies this query.
        self.assertIsNone(todo._solo_term_id_prefix_hit(["cafefeed", "widget"], self.IDS))

    def test_short_term_is_not_attempted(self) -> None:
        # Below the 4-hex-char selector convention -- too easy to collide by chance.
        self.assertIsNone(todo._solo_term_id_prefix_hit(["caf"], self.IDS))

    def test_non_hex_term_is_not_attempted(self) -> None:
        self.assertIsNone(todo._solo_term_id_prefix_hit(["quokka"], self.IDS))


class SoloTermIdPrefixSearchTest(TodoCase):
    """End-to-end: `search` pins a unique id-prefix hit first."""

    def _set_config(self, **keys) -> None:
        config = json.loads((self._db_dir / "config.json").read_text(encoding="utf-8"))
        config.update(keys)
        (self._db_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")

    def test_unique_id_prefix_hit_is_pinned_first(self) -> None:
        # Lexical and vector ranking are both off, so the hit can only come
        # from the id-prefix path -- nothing else could surface a bare hex
        # token that shares no word with any Summary.
        self._set_config(embedder=None)
        target = "cafefeed" + "0" * 56
        self.write_ticket(f"{target[:8]}-target", target, summary="zzz unrelated summary text")
        for n in range(3):
            filler = f"1234000{n}" + "0" * 56
            self.write_ticket(f"{filler[:8]}-filler{n}", filler, summary="widget maintenance")
        proc = self.todo("search", "cafefeed")
        self.assertEqual(0, proc.returncode, proc.stderr)
        first_line = proc.stdout.strip().splitlines()[0]
        self.assertIn("cafefeed", first_line, f"expected id hit pinned first:\n{proc.stdout}")

    def test_prefix_matching_nothing_falls_back_without_error(self) -> None:
        self._set_config(embedder=None)
        self.write_ticket("target", "cafefeed" + "0" * 56, summary="widget one")
        proc = self.todo("search", "deadbeef")
        self.assertEqual(0, proc.returncode, proc.stderr)
        self.assertNotIn("deadbeef", proc.stdout)


class StopwordDiscoveryCliTest(TodoCase):
    """Discovery through the binary: what lands in config.json, and when."""

    def _config(self) -> dict:
        return json.loads((self._db_dir / "config.json").read_text(encoding="utf-8"))

    def _seed_corpus(self) -> None:
        """Nine todos about widgets, one about a quokka."""
        for n in range(9):
            tid = self.mint()
            self.write_ticket(f"{tid[:8]}-w{n}", tid, summary=f"widget maintenance {n}")
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-q", tid, summary="quokka sighting")

    def _search(self, *args: str) -> str:
        proc = self.todo("search", *args, "--embedder", "apple")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_search_discovers_and_persists_stopwords(self) -> None:
        self._seed_corpus()
        self.assertNotIn("search_stopwords", self._config())
        self._search("widget")
        stopwords = self._config()["search_stopwords"]
        self.assertIn("widget", stopwords)
        self.assertNotIn("quokka", stopwords)

    def test_a_hand_edited_list_is_honored_not_overwritten(self) -> None:
        # Discovery is lazy: a list that already exists is reused verbatim, so
        # editing config.json is a supported way to control the ranker.
        self._seed_corpus()
        config = self._config()
        config["search_stopwords"] = ["quokka"]
        (self._db_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
        self._search("widget")
        self.assertEqual(["quokka"], self._config()["search_stopwords"])

    def test_dry_run_discovers_without_persisting(self) -> None:
        self._seed_corpus()
        proc = self.todo("search", "widget", "--embedder", "apple", "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("search_stopwords", self._config())

    def test_threshold_is_configurable(self) -> None:
        # A threshold of 0 means nothing is common enough to be a stopword.
        self._seed_corpus()
        config = self._config()
        config["search_stopword_min_idf"] = 0.0
        (self._db_dir / "config.json").write_text(json.dumps(config), encoding="utf-8")
        self._search("widget")
        self.assertFalse(self._config().get("search_stopwords"))


class ClearSearchDataTest(TodoCase):
    """Derived data is droppable: what goes, what stays, and what comes back."""

    def _config(self) -> dict:
        return json.loads((self._db_dir / "config.json").read_text(encoding="utf-8"))

    def _vectors(self) -> int:
        db = self._db_dir / "sqlite.db"
        if not db.exists():
            return 0
        conn = sqlite3.connect(str(db))
        try:
            return conn.execute("SELECT COUNT(*) FROM embeddings").fetchone()[0]
        finally:
            conn.close()

    def _seed(self, n: int = 3) -> str:
        last = ""
        for i in range(n):
            tid = self.mint()
            self.write_ticket(f"{tid[:8]}-s{i}", tid, summary=f"quokka sighting {i}")
            last = tid
        return last

    def _search(self) -> None:
        proc = self.todo("search", "quokka", "--embedder", "apple")
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_clear_all_drops_vectors_and_the_stopword_list(self) -> None:
        self._seed()
        self._search()
        self.assertGreater(self._vectors(), 0)
        self.assertTrue(self._config().get("search_stopwords"))

        proc = self.todo("clear-search-data", "ALL")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(0, self._vectors())
        self.assertFalse(self._config().get("search_stopwords"))

    def test_cleared_vectors_come_back_on_the_next_search(self) -> None:
        self._seed()
        self._search()
        before = self._vectors()
        self.todo("clear-search-data", "ALL")
        self._search()
        self.assertEqual(before, self._vectors(), "re-derive should restore the vectors")

    def test_clear_strips_vectors_stamped_into_the_ticket_json(self) -> None:
        # The index is not the only copy -- vectors are stamped into the record
        # too, and a clear that missed those would leave search re-reading them.
        tid = self._seed(1)
        self._search()
        record = json.loads(self.todo("read", tid).stdout)
        self.assertTrue([k for k in record["Summary"] if k != "raw"], "expected stamped vectors")
        self.todo("clear-search-data", "ALL")
        record = json.loads(self.todo("read", tid).stdout)
        self.assertEqual(["raw"], [k for k in record["Summary"] if k != "objid"])

    def test_clearing_one_todo_leaves_the_corpus_stopword_list_alone(self) -> None:
        # The list is a property of the corpus, not of any one todo.
        tid = self._seed()
        self._search()
        self.todo("clear-search-data", tid[:8])
        self.assertTrue(self._config().get("search_stopwords"))

    def test_selector_is_required(self) -> None:
        proc = self.todo("clear-search-data")
        self.assertNotEqual(0, proc.returncode)


if __name__ == "__main__":
    unittest.main()
