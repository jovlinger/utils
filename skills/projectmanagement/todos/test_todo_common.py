"""Unit tests that call the common core directly: todo_common, todo_search, todo_db.

The CLI-driven tests of the same features live with the todo suite
(test_todo.py, test_todo_search.py, test_todo_tag_impl.py).
"""

# Test names carry the intent, and the private helpers are the unit under test.
# pylint: disable=missing-class-docstring,missing-function-docstring,protected-access

from __future__ import annotations

import unittest
import unittest.mock
from typing import Any, Dict

import todo_common
import todo_db
import todo_search


def _raws(todo_dict: Dict[str, Any]) -> list:
    return [e["raw"] for e in todo_dict.get("Tag", [])]


class RepoIdentityUnitTests(unittest.TestCase):
    """Pure-function tests for the stable repo identity derivation."""

    def test_url_shapes_canonicalize_to_same_identity(self) -> None:
        want = "github.com/jovlinger/utils"
        self.assertEqual(
            todo_common.repo_identity_from_url(
                "https://github.com/jovlinger/utils.git"
            ),
            want,
        )
        self.assertEqual(
            todo_common.repo_identity_from_url("https://github.com/jovlinger/utils"),
            want,
        )
        self.assertEqual(
            todo_common.repo_identity_from_url("git@github.com:jovlinger/utils.git"),
            want,
        )
        self.assertEqual(
            todo_common.repo_identity_from_url(
                "ssh://git@github.com/jovlinger/utils.git"
            ),
            want,
        )

    def test_host_is_lowercased_and_owner_preserved(self) -> None:
        self.assertEqual(
            todo_common.repo_identity_from_url(
                "git@GitHub.com:easternlabs/opportunity.git"
            ),
            "github.com/easternlabs/opportunity",
        )

    def test_unidentifiable_urls_return_none(self) -> None:
        self.assertIsNone(todo_common.repo_identity_from_url(""))
        self.assertIsNone(todo_common.repo_identity_from_url("   "))
        self.assertIsNone(todo_common.repo_identity_from_url("not a url"))


class ParseSearchQueryTest(unittest.TestCase):
    """Colon-based time operators are stripped; text terms pass through."""

    def test_strips_time_operators_and_keeps_text(self) -> None:
        terms, filters = todo_common.parse_search_query(
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
        _terms, filters = todo_common.parse_search_query(
            [
                "tu_after:2026-06-01T12:00:00Z",
                "tu_before:2026-06-30T12:00:00Z",
            ]
        )
        self.assertEqual(filters.update_after, "2026-06-01T12:00:00Z")
        self.assertEqual(filters.update_before, "2026-06-30T12:00:00Z")

    def test_unknown_colon_token_is_a_text_term(self) -> None:
        terms, _filters = todo_common.parse_search_query(["foo:bar"])
        self.assertEqual(terms, ["foo:bar"])

    def test_date_only_expands_to_day_bounds(self) -> None:
        _terms, filters = todo_common.parse_search_query(
            [
                "tc_after:2026-08-25",
                "tc_before:2026-08-31",
            ]
        )
        self.assertEqual(filters.create_after, "2026-08-25T00:00:00Z")
        self.assertEqual(filters.create_before, "2026-08-31T23:59:59Z")

    def test_slash_dates_normalize_to_hyphens(self) -> None:
        _terms, filters = todo_common.parse_search_query(["tc_after:2026/08/26"])
        self.assertEqual(filters.create_after, "2026-08-26T00:00:00Z")

    def test_invalid_timestamp_errors(self) -> None:
        with self.assertRaises(todo_common.TodoError):
            todo_common.parse_search_query(["tc_after:not-a-date"])

    def test_empty_operator_value_errors(self) -> None:
        with self.assertRaises(todo_common.TodoError):
            todo_common.parse_search_query(["tc_after:"])


class SoloTermIdPrefixHitTest(unittest.TestCase):
    """Unit coverage for the helper search_tickets consults for a solo term."""

    IDS = {"cafefeed" + "0" * 56: {}, "deadbeef" + "0" * 56: {}}

    def test_unique_prefix_match_is_returned(self) -> None:
        hit = todo_common._solo_term_id_prefix_hit(["cafefeed"], self.IDS)
        self.assertEqual("cafefeed" + "0" * 56, hit)

    def test_full_id_also_matches(self) -> None:
        full = "cafefeed" + "0" * 56
        self.assertEqual(full, todo_common._solo_term_id_prefix_hit([full], self.IDS))

    def test_no_match_returns_none(self) -> None:
        self.assertIsNone(todo_common._solo_term_id_prefix_hit(["ffffffff"], self.IDS))

    def test_ambiguous_match_returns_none(self) -> None:
        ids = {"aaaa1111" + "0" * 56: {}, "aaaa2222" + "0" * 56: {}}
        self.assertIsNone(todo_common._solo_term_id_prefix_hit(["aaaa"], ids))

    def test_multiple_terms_never_engage_the_prefix_path(self) -> None:
        # A second term would otherwise win uniquely -- proving it is the term
        # COUNT, not the match, that disqualifies this query.
        self.assertIsNone(
            todo_common._solo_term_id_prefix_hit(["cafefeed", "widget"], self.IDS)
        )

    def test_short_term_is_not_attempted(self) -> None:
        # Below the 4-hex-char selector convention -- too easy to collide by chance.
        self.assertIsNone(todo_common._solo_term_id_prefix_hit(["caf"], self.IDS))

    def test_non_hex_term_is_not_attempted(self) -> None:
        self.assertIsNone(todo_common._solo_term_id_prefix_hit(["quokka"], self.IDS))


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
        self.assertEqual(
            todo_search.tokenize("bh 791 / ead99397"), ["bh", "791", "ead99397"]
        )

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
        scores = self._index(phrase="alpha beta", split="beta gamma alpha").score(
            ["alpha beta"]
        )
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
            self.assertEqual(
                todo_search.tokenize("merging tickets"), ["MERGING", "TICKETS"]
            )
        # ...and the default is restored afterwards, so the seam is not sticky.
        self.assertEqual(todo_search.tokenize("merging"), [todo_search.stem("merging")])

    def test_default_stemmer_is_the_documented_one(self) -> None:
        self.assertIs(todo_search.STEMMER, todo_search.stem)


class MigrateRecordV7Tests(unittest.TestCase):
    """Unit coverage for todo_db.migrate_record_v7 beyond the oracle's pinned case."""

    def test_no_tags_key_is_a_no_op(self) -> None:
        rec = {"Id": "a" * 64, "_schema": 6}
        out = todo_db.migrate_record_v7(dict(rec))
        self.assertNotIn("Tag", out)

    def test_non_list_tags_dropped_without_crashing(self) -> None:
        out = todo_db.migrate_record_v7({"Tags": "not-a-list"})
        self.assertNotIn("Tags", out)
        self.assertNotIn("Tag", out)

    def test_merges_into_existing_tag_elements(self) -> None:
        rec = {
            "Tag": [{"raw": "existing", "manual": True}],
            "Tags": ["existing", "new"],
        }
        out = todo_db.migrate_record_v7(rec)
        self.assertNotIn("Tags", out)
        self.assertEqual(sorted(_raws(out)), ["existing", "new"])  # deduped, merged

    def test_reachable_via_migrate_record_and_bumps_schema(self) -> None:
        rec = {"Id": "a" * 64, "Tags": ["X"]}
        out = todo_db.migrate_record(rec)
        self.assertEqual(out["_schema"], todo_db.SCHEMA_VERSION)
        self.assertEqual(_raws(out), ["x"])


class EmbedTargetsUnitTests(unittest.TestCase):
    """Direct coverage for the plural-Tag embedding plumbing in todo_common."""

    def test_embed_targets_includes_summary_body_and_each_tag(self) -> None:
        d = {
            "Summary": {"raw": "s"},
            "Body": {"raw": "b"},
            "Tag": [{"raw": "one", "manual": True}, {"raw": "two", "manual": True}],
        }
        targets = todo_common._embed_targets(d)
        paths = [path for path, _container, _raw in targets]
        self.assertEqual(paths, ["Summary.raw", "Body.raw", "Tag.0.raw", "Tag.1.raw"])

    def test_embed_targets_skips_blank_tag_raw(self) -> None:
        d = {"Tag": [{"raw": "", "manual": True}, {"raw": "kept", "manual": True}]}
        targets = todo_common._embed_targets(d)
        self.assertEqual([p for p, _c, _r in targets], ["Tag.1.raw"])

    def test_container_at_resolves_tag_index_and_missing_index(self) -> None:
        d = {"Tag": [{"raw": "one", "manual": True}]}
        self.assertIs(todo_common._container_at(d, "Tag.0.raw"), d["Tag"][0])
        self.assertIsNone(todo_common._container_at(d, "Tag.5.raw"))
        self.assertIsNone(todo_common._container_at(d, "Tag.not-an-index.raw"))

    def test_container_at_resolves_summary(self) -> None:
        d = {"Summary": {"raw": "s"}}
        self.assertIs(todo_common._container_at(d, "Summary.raw"), d["Summary"])

    def test_changed_raw_fields_flags_new_and_edited_tag(self) -> None:
        old = {"Tag": [{"raw": "one", "manual": True}]}
        new = {
            "Tag": [
                {"raw": "one-edited", "manual": True},
                {"raw": "two", "manual": True},
            ]
        }
        changed = set(todo_common._changed_raw_fields(old, new))
        self.assertIn("Tag.0.raw", changed)  # same position, raw text differs
        self.assertIn("Tag.1.raw", changed)  # newly present

    def test_changed_raw_fields_empty_for_identical_tags(self) -> None:
        same = {"Tag": [{"raw": "one", "manual": True}]}
        self.assertEqual(todo_common._changed_raw_fields(same, dict(same)), [])


if __name__ == "__main__":
    unittest.main()
