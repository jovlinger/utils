#!/usr/bin/env python3
"""Implementor tests for the plural, provenance-tracked Tag field (ee1799aa).

Covers what test_todo_tag.py (the frozen oracle) leaves to the implementor:
per-element embedding on write, clear-on-write when a tag's raw changes,
search ranking picking up a Tag match, the ported zero-shot tag mining/scoring
(_split_phrases/_nphrase_windows/_mine_tag_candidates/compute_auto_tags),
cross-field invalidation of AUTOMATIC tags on a Summary/Body edit, and
doctor's automatic-tag recompute. Also carries extra unit coverage for
apply_tag_add/apply_tag_remove/tag_findings/migrate_record_v7 beyond the
oracle's pinned cases (whitespace handling, merge-on-migrate, etc).

Run with:
    python3 -m unittest test_todo_tag_impl -v
"""

from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
import unittest
from typing import Any, Dict

import fake_nlce
import todo
import todo_db

from test_todo import BOW, TODO_PY, TodoCase


def _raws(todo_dict: Dict[str, Any]) -> list:
    return [e["raw"] for e in todo_dict.get("Tag", [])]


class ApplyTagAddTests(unittest.TestCase):
    """Unit coverage for todo.apply_tag_add beyond the oracle's pinned cases."""

    def test_strips_and_downcases(self) -> None:
        d: Dict[str, Any] = {}
        todo.apply_tag_add(d, "  Mixed CASE  ")
        self.assertEqual(_raws(d), ["mixed case"])
        self.assertTrue(d["Tag"][0]["manual"])

    def test_blank_and_non_string_args_ignored(self) -> None:
        d: Dict[str, Any] = {}
        todo.apply_tag_add(d, "", "   ", "real")
        self.assertEqual(_raws(d), ["real"])

    def test_dedupes_within_one_call(self) -> None:
        d: Dict[str, Any] = {}
        todo.apply_tag_add(d, "Dup", "dup", "DUP")
        self.assertEqual(_raws(d), ["dup"])

    def test_leaves_existing_automatic_elements_untouched(self) -> None:
        d: Dict[str, Any] = {"Tag": [{"raw": "auto one", "manual": False}]}
        todo.apply_tag_add(d, "manual one")
        self.assertEqual(sorted(_raws(d)), ["auto one", "manual one"])
        by_raw = {e["raw"]: e["manual"] for e in d["Tag"]}
        self.assertEqual(by_raw, {"auto one": False, "manual one": True})

    def test_does_not_duplicate_an_existing_automatic_tags_text(self) -> None:
        d: Dict[str, Any] = {"Tag": [{"raw": "shared", "manual": False}]}
        todo.apply_tag_add(d, "Shared")
        self.assertEqual(_raws(d), ["shared"])  # no duplicate manual element added
        self.assertFalse(d["Tag"][0]["manual"])  # the existing element is untouched


class ApplyTagRemoveTests(unittest.TestCase):
    """Unit coverage for todo.apply_tag_remove beyond the oracle's pinned cases."""

    def test_no_op_when_tag_absent(self) -> None:
        d: Dict[str, Any] = {"Summary": {"raw": "s"}}
        todo.apply_tag_remove(d, "anything")
        self.assertNotIn("Tag", d)

    def test_no_op_for_unmatched_tag(self) -> None:
        d: Dict[str, Any] = {"Tag": [{"raw": "one", "manual": True}]}
        todo.apply_tag_remove(d, "two")
        self.assertEqual(_raws(d), ["one"])

    def test_blank_and_non_string_args_ignored(self) -> None:
        d: Dict[str, Any] = {"Tag": [{"raw": "one", "manual": True}]}
        todo.apply_tag_remove(d, "", "   ")
        self.assertEqual(_raws(d), ["one"])

    def test_removes_multiple_in_one_call(self) -> None:
        d: Dict[str, Any] = {}
        todo.apply_tag_add(d, "one", "two", "three")
        todo.apply_tag_remove(d, "One", "THREE")
        self.assertEqual(_raws(d), ["two"])


class TagFindingsTests(unittest.TestCase):
    """Unit coverage for todo.tag_findings beyond the oracle's pinned cases."""

    def test_absent_tag_is_fine(self) -> None:
        self.assertEqual(todo.tag_findings({"Summary": {"raw": "s"}}), [])

    def test_empty_list_is_fine(self) -> None:
        self.assertEqual(todo.tag_findings({"Tag": []}), [])

    def test_multiple_elements_all_valid(self) -> None:
        good = {"Tag": [{"raw": "a", "manual": True}, {"raw": "b", "manual": False}]}
        self.assertEqual(todo.tag_findings(good), [])

    def test_reports_one_finding_per_bad_element_by_index(self) -> None:
        bad = {"Tag": [{"raw": "ok", "manual": True}, {"raw": 5, "manual": "nope"}]}
        findings = todo.tag_findings(bad)
        self.assertIn("Tag.1.raw must be a non-empty string", findings)
        self.assertIn("Tag.1.manual must be a bool", findings)
        self.assertEqual(len(findings), 2)  # element 0 is clean

    def test_non_dict_element_reported_and_skipped(self) -> None:
        findings = todo.tag_findings({"Tag": ["not-a-dict"]})
        self.assertEqual(findings, ["Tag.0 must be an object"])


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
        rec = {"Tag": [{"raw": "existing", "manual": True}], "Tags": ["existing", "new"]}
        out = todo_db.migrate_record_v7(rec)
        self.assertNotIn("Tags", out)
        self.assertEqual(sorted(_raws(out)), ["existing", "new"])  # deduped, merged

    def test_reachable_via_migrate_record_and_bumps_schema(self) -> None:
        rec = {"Id": "a" * 64, "Tags": ["X"]}
        out = todo_db.migrate_record(rec)
        self.assertEqual(out["_schema"], todo_db.SCHEMA_VERSION)
        self.assertEqual(_raws(out), ["x"])


class EmbedTargetsUnitTests(unittest.TestCase):
    """Direct coverage for the plural-Tag embedding plumbing in todo.py."""

    def test_embed_targets_includes_summary_body_and_each_tag(self) -> None:
        d = {
            "Summary": {"raw": "s"},
            "Body": {"raw": "b"},
            "Tag": [{"raw": "one", "manual": True}, {"raw": "two", "manual": True}],
        }
        targets = todo._embed_targets(d)
        paths = [path for path, _container, _raw in targets]
        self.assertEqual(paths, ["Summary.raw", "Body.raw", "Tag.0.raw", "Tag.1.raw"])

    def test_embed_targets_skips_blank_tag_raw(self) -> None:
        d = {"Tag": [{"raw": "", "manual": True}, {"raw": "kept", "manual": True}]}
        targets = todo._embed_targets(d)
        self.assertEqual([p for p, _c, _r in targets], ["Tag.1.raw"])

    def test_container_at_resolves_tag_index_and_missing_index(self) -> None:
        d = {"Tag": [{"raw": "one", "manual": True}]}
        self.assertIs(todo._container_at(d, "Tag.0.raw"), d["Tag"][0])
        self.assertIsNone(todo._container_at(d, "Tag.5.raw"))
        self.assertIsNone(todo._container_at(d, "Tag.not-an-index.raw"))

    def test_container_at_resolves_summary(self) -> None:
        d = {"Summary": {"raw": "s"}}
        self.assertIs(todo._container_at(d, "Summary.raw"), d["Summary"])

    def test_changed_raw_fields_flags_new_and_edited_tag(self) -> None:
        old = {"Tag": [{"raw": "one", "manual": True}]}
        new = {"Tag": [{"raw": "one-edited", "manual": True}, {"raw": "two", "manual": True}]}
        changed = set(todo._changed_raw_fields(old, new))
        self.assertIn("Tag.0.raw", changed)  # same position, raw text differs
        self.assertIn("Tag.1.raw", changed)  # newly present

    def test_changed_raw_fields_empty_for_identical_tags(self) -> None:
        same = {"Tag": [{"raw": "one", "manual": True}]}
        self.assertEqual(todo._changed_raw_fields(same, dict(same)), [])


class TagEmbeddingIntegrationTests(TodoCase):
    """End-to-end: search stamps per-element vectors; edits clear them; search ranks by tag.

    Tag elements used to be embedded eagerly by tag-add, back when the lexical
    `hash` backend was cheap. Nothing is cheap now, so the per-element vectors are
    produced by search's lazy backfill instead -- the field_path bookkeeping under
    test (one Tag.<i>.raw path per element, cleared per element on edit) is the
    same either way.
    """

    def _emb_rows(self) -> list:
        conn = sqlite3.connect(str(self._db_dir / "sqlite.db"))
        try:
            return conn.execute(
                "SELECT ticket_id, field_path, embedder FROM embeddings"
            ).fetchall()
        finally:
            conn.close()

    def _set_json_path(self, *args: str, stdin: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(TODO_PY), "set-json-path", *args],
            cwd=str(self.repo), input=stdin, capture_output=True, text=True,
            check=False, env=self._env,
        )

    def test_search_stamps_vector_for_a_tag_element(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="x")
        proc = self.todo("tag-add", self.tid, "Billing")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ticket = self.read_cur()
        self.assertEqual(ticket["Tag"][0]["raw"], "billing")
        self.assertNotIn(BOW, ticket["Tag"][0])  # no cheap embedder: not stamped yet
        search = self.todo("search", "billing", "--embedder", "apple")
        self.assertEqual(search.returncode, 0, search.stderr)
        self.assertIn(BOW, self.read_cur()["Tag"][0])  # backfilled inline
        self.assertIn((tid, "Tag.0.raw", BOW), self._emb_rows())

    def test_two_tags_get_independent_field_paths(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="x")
        proc = self.todo("tag-add", self.tid, "alpha", "beta")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        search = self.todo("search", "alpha", "--embedder", "apple")
        self.assertEqual(search.returncode, 0, search.stderr)
        rows = {(field, emb) for _t, field, emb in self._emb_rows()}
        self.assertIn(("Tag.0.raw", BOW), rows)
        self.assertIn(("Tag.1.raw", BOW), rows)

    def test_editing_a_tags_raw_clears_only_that_elements_vectors(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="x")
        proc = self.todo("tag-add", self.tid, "alpha", "beta")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        # Inject stale expensive vectors as if a prior search had backfilled them.
        stale = "apple_nlce:x:r1:pool=mean:norm=l2:v1"
        conn = sqlite3.connect(str(self._db_dir / "sqlite.db"))
        conn.execute(
            "INSERT INTO embeddings(ticket_id, field_path, embedder, vector) VALUES (?,?,?,?)",
            (tid, "Tag.0.raw", stale, b"\x00\x00\x00\x00"),
        )
        conn.execute(
            "INSERT INTO embeddings(ticket_id, field_path, embedder, vector) VALUES (?,?,?,?)",
            (tid, "Tag.1.raw", stale, b"\x00\x00\x00\x00"),
        )
        conn.commit()
        conn.close()
        # Edit element 0's raw in place; element 1 is untouched.
        proc = self._set_json_path(self.tid, "Tag.0.raw", stdin='"gamma"')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = self._emb_rows()
        tag0_embedders = {emb for _t, field, emb in rows if field == "Tag.0.raw"}
        tag1_embedders = {emb for _t, field, emb in rows if field == "Tag.1.raw"}
        self.assertNotIn(stale, tag0_embedders)  # cleared: this element's raw changed
        self.assertEqual(tag0_embedders, set())  # nothing cheap repopulates it
        self.assertIn(stale, tag1_embedders)  # untouched: a different element
        # get-json-path (not read/read_cur): it never merges the sqlite
        # embeddings index, so the still-injected 4-byte fake "stale" blob on
        # Tag.1.raw (never a validly packed vector -- read would try to unpack
        # it) does not need to be touched to check the raw text landed right.
        first = self.todo("get-json-path", self.tid, "Tag.0.raw")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), "gamma")
        second = self.todo("get-json-path", self.tid, "Tag.1.raw")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.strip(), "beta")

    def test_search_ranks_todo_whose_tag_matches_the_query(self) -> None:
        tagged = self.mint()
        self.write_ticket(f"{tagged[:8]}-a", tagged, summary="unrelated summary text")
        proc = self.todo("tag-add", self.tid, "gizmo-widget")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        untagged = self.mint()
        self.write_ticket(f"{untagged[:8]}-b", untagged, summary="also unrelated text")
        proc = self.todo("search", "gizmo-widget", "--embedder", "apple")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(tagged[:8], proc.stdout)
        self.assertNotIn(untagged[:8], proc.stdout)

    def test_tagrm_drops_field_and_no_longer_ranks(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="unrelated summary text")
        proc = self.todo("tag-add", self.tid, "unique-marker-xyz")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.todo("search", "unique-marker-xyz", "--embedder", "apple")
        self.assertIn(tid[:8], proc.stdout)
        proc = self.todo("tag-rm", self.tid, "unique-marker-xyz")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Tag", self.read_cur())
        proc = self.todo("search", "unique-marker-xyz", "--embedder", "apple")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(tid[:8], proc.stdout)


class TagCliRoundTripTests(TodoCase):
    """tagadd/tagrm as a black-box: idempotence, dedup, manual-only removal."""

    def test_tagadd_idempotent_and_deduped(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="x")
        self.todo("tag-add", self.tid, "Todo Tool")
        self.todo("tag-add", self.tid, "todo tool")
        proc = self.todo("tag-add", self.tid, "Embeddings")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(sorted(_raws(self.read_cur())), ["embeddings", "todo tool"])

    def test_tagrm_leaves_automatic_tag_via_cli(self) -> None:
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-a",
            tid,
            summary="x",
            extra={"Tag": [{"raw": "auto one", "manual": False}]},
        )
        proc = self.todo("tag-rm", self.tid, "auto one")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("auto one", _raws(self.read_cur()))

    def test_doctor_ok_for_well_formed_tag(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="x")
        self.todo("tag-add", self.tid, "ok")
        proc = self.todo("doctor", self.tid)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])


class ComputeAutoTagsTests(unittest.TestCase):
    """Unit coverage for todo.compute_auto_tags beyond the oracle's pinned case."""

    def setUp(self) -> None:
        # Bag-of-words double: scoring is by shared tokens, which is what these
        # ranking assertions are written against (was get_embedder("hash")).
        self.embedder = fake_nlce.BowEmbedder()

    def test_top_k_are_automatic_elements_whose_raw_is_a_candidate(self) -> None:
        candidates = ["alpha beta", "gamma", "delta epsilon", "zeta"]
        elems = todo.compute_auto_tags("alpha beta gamma", candidates, self.embedder, 2)
        self.assertEqual(len(elems), 2)
        self.assertTrue(all(e["manual"] is False for e in elems))
        self.assertTrue(all(e["raw"] in candidates for e in elems))

    def test_best_match_ranks_first(self) -> None:
        candidates = ["alpha beta gamma", "totally unrelated words"]
        elems = todo.compute_auto_tags("alpha beta gamma", candidates, self.embedder, 1)
        self.assertEqual(elems, [{"raw": "alpha beta gamma", "manual": False}])

    def test_k_larger_than_candidate_pool_returns_all_of_them(self) -> None:
        elems = todo.compute_auto_tags("one two", ["one", "two"], self.embedder, 5)
        self.assertEqual(len(elems), 2)

    def test_empty_candidates_returns_empty(self) -> None:
        self.assertEqual(todo.compute_auto_tags("text", [], self.embedder, 3), [])

    def test_tie_break_is_deterministic_by_candidate_text(self) -> None:
        # "zulu alpha" and "alpha zulu" are the same bag of words, so BowEmbedder
        # scores them identically against "alpha zulu" -- a tie
        # that must break on candidate text (ascending), not input order.
        candidates = ["zulu alpha", "alpha zulu"]
        elems = todo.compute_auto_tags("alpha zulu", candidates, self.embedder, 1)
        self.assertEqual(elems[0]["raw"], "alpha zulu")


class PhraseMiningTests(unittest.TestCase):
    """Ported _split_phrases/_nphrase_windows/_mine_tag_candidates on small inputs."""

    def test_split_phrases_splits_on_sentence_terminators_and_newlines(self) -> None:
        text = "First sentence. Second one!\nThird line\n\nFourth."
        self.assertEqual(
            todo._split_phrases(text),
            ["First sentence", "Second one", "Third line", "Fourth"],
        )

    def test_split_phrases_keeps_a_decimal_intact(self) -> None:
        self.assertEqual(todo._split_phrases("version 3.5 released"), ["version 3.5 released"])

    def test_nphrase_windows_covers_1_through_max_n_contiguous_windows(self) -> None:
        self.assertEqual(
            todo._nphrase_windows("one. two. three."),
            ["one", "two", "three", "one two", "two three", "one two three"],
        )

    def test_nphrase_windows_respects_a_smaller_max_n(self) -> None:
        self.assertEqual(
            todo._nphrase_windows("a. b. c.", max_n=2),
            ["a", "b", "c", "a b", "b c"],
        )

    def test_mine_tag_candidates_downcases_dedupes_first_seen_order(self) -> None:
        raws = {
            "t1": {"Summary.raw": "Alpha Beta. Gamma."},
            "t2": {"Summary.raw": "gamma. Alpha beta."},
        }
        candidates = todo._mine_tag_candidates(raws)
        self.assertEqual(candidates[0], "alpha beta")  # first-seen, downcased
        self.assertIn("alpha beta gamma", candidates)
        # t2 contributes no duplicate of the already-seen downcased phrases
        self.assertEqual(candidates.count("gamma"), 1)
        self.assertEqual(candidates.count("alpha beta"), 1)


class CrossFieldTagInvalidationTests(TodoCase):
    """Editing Summary/Body drops AUTOMATIC Tag elements; MANUAL ones survive."""

    def test_editing_summary_drops_automatic_tags_keeps_manual(self) -> None:
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-a",
            tid,
            summary="original summary",
            extra={
                "Tag": [
                    {"raw": "manual one", "manual": True},
                    {"raw": "auto one", "manual": False},
                ]
            },
        )
        proc = self.todo("set", self.tid, "--summary", "a whole new summary")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ticket = self.read_cur()
        self.assertEqual(_raws(ticket), ["manual one"])
        self.assertTrue(ticket["Tag"][0]["manual"])

    def test_editing_body_drops_the_only_automatic_tag(self) -> None:
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-a",
            tid,
            summary="s",
            body="original body",
            extra={"Tag": [{"raw": "auto one", "manual": False}]},
        )
        proc = self.todo("set", self.tid, "--body", "a whole new body")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Tag", self.read_cur())  # only element was automatic -> field dropped

    def test_unrelated_field_edit_leaves_automatic_tags(self) -> None:
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-a",
            tid,
            summary="s",
            extra={"Tag": [{"raw": "auto one", "manual": False}]},
        )
        proc = self.todo("set", self.tid, "--ac", "some acceptance criteria")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("auto one", _raws(self.read_cur()))

    def test_no_clear_preserves_automatic_tags_despite_summary_edit(self) -> None:
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-a",
            tid,
            summary="original summary",
            extra={"Tag": [{"raw": "auto one", "manual": False}]},
        )
        proc = self.todo("set", self.tid, "--summary", "trivial rewording", "--no-clear")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("auto one", _raws(self.read_cur()))


class ApplyTagClearTests(unittest.TestCase):
    """Unit coverage for todo.apply_tag_clear: which provenance goes, which stays."""

    def _both(self) -> Dict[str, Any]:
        return {
            "Tag": [
                {"raw": "manual one", "manual": True},
                {"raw": "auto one", "manual": False},
                {"raw": "auto two", "manual": False},
            ]
        }

    def test_default_removes_automatic_only(self) -> None:
        d = self._both()
        self.assertEqual(todo.apply_tag_clear(d), 2)
        self.assertEqual(_raws(d), ["manual one"])

    def test_include_manual_removes_everything_and_drops_field(self) -> None:
        d = self._both()
        self.assertEqual(todo.apply_tag_clear(d, include_manual=True), 3)
        self.assertNotIn("Tag", d)  # optional fields are absent, not []

    def test_field_dropped_when_only_automatic_present(self) -> None:
        d = {"Tag": [{"raw": "auto one", "manual": False}]}
        self.assertEqual(todo.apply_tag_clear(d), 1)
        self.assertNotIn("Tag", d)

    def test_no_tags_is_a_no_op(self) -> None:
        d: Dict[str, Any] = {}
        self.assertEqual(todo.apply_tag_clear(d, include_manual=True), 0)
        self.assertNotIn("Tag", d)

    def test_manual_only_survives_the_default(self) -> None:
        d = {"Tag": [{"raw": "keep", "manual": True}]}
        self.assertEqual(todo.apply_tag_clear(d), 0)
        self.assertEqual(_raws(d), ["keep"])


class TagClearCliTests(TodoCase):
    """tag-clear end to end: provenance scoping, selector scoping, corpus default."""

    def _seed(self, name: str, tags: list) -> str:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-{name}", tid, summary=name, extra={"Tag": tags})
        return tid

    def _tags_of(self, tid: str) -> list:
        proc = self.todo("read", tid[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return _raws(json.loads(proc.stdout))

    def test_default_clears_automatic_and_keeps_manual(self) -> None:
        tid = self._seed(
            "mixed",
            [{"raw": "keep me", "manual": True}, {"raw": "drop me", "manual": False}],
        )
        proc = self.todo("tag-clear", tid[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertFalse(payload["include_manual"])
        self.assertEqual(payload["tags_removed"], 1)
        self.assertEqual(payload["todos_cleared"], 1)
        self.assertEqual(self._tags_of(tid), ["keep me"])

    def test_all_flag_clears_manual_too(self) -> None:
        tid = self._seed(
            "mixed",
            [{"raw": "keep me", "manual": True}, {"raw": "drop me", "manual": False}],
        )
        proc = self.todo("tag-clear", tid[:8], "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertTrue(payload["include_manual"])
        self.assertEqual(payload["tags_removed"], 2)
        self.assertEqual(self._tags_of(tid), [])

    def test_explicit_selector_leaves_other_todos_alone(self) -> None:
        target = self._seed("target", [{"raw": "t", "manual": True}])
        other = self._seed("other", [{"raw": "o", "manual": True}])
        proc = self.todo("tag-clear", target[:8], "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["scanned"], 1)
        self.assertEqual(self._tags_of(target), [])
        self.assertEqual(self._tags_of(other), ["o"])

    def test_omitted_selector_clears_the_whole_corpus(self) -> None:
        first = self._seed("first", [{"raw": "a", "manual": True}])
        second = self._seed("second", [{"raw": "b", "manual": False}])
        untagged = self._seed("untagged", [])
        proc = self.todo("tag-clear", "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["scanned"], 3)
        self.assertEqual(payload["todos_cleared"], 2)  # the untagged one is skipped
        self.assertEqual(payload["tags_removed"], 2)
        self.assertEqual(self._tags_of(first), [])
        self.assertEqual(self._tags_of(second), [])
        self.assertEqual(self._tags_of(untagged), [])

    def test_ALL_sentinel_is_the_same_as_omitting_the_selector(self) -> None:
        tid = self._seed("one", [{"raw": "x", "manual": False}])
        proc = self.todo("tag-clear", "ALL")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout)["tags_removed"], 1)
        self.assertEqual(self._tags_of(tid), [])

    def test_untouched_todo_keeps_its_update_dt(self) -> None:
        tid = self._seed("untagged", [])
        before = json.loads(self.todo("read", tid[:8]).stdout)["update_dt"]
        proc = self.todo("tag-clear", tid[:8], "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["todos_cleared"], 0)
        self.assertEqual(payload["results"], [])
        after = json.loads(self.todo("read", tid[:8]).stdout)["update_dt"]
        self.assertEqual(before, after)  # no write, so no update_dt bump

    def test_corpus_sweep_does_not_move_a_foreign_repo_todo(self) -> None:
        # The store is shared across repos and sqlite keys tickets by
        # (repo_path, branch), so a `tag-clear ALL` run from THIS repo must write a
        # foreign-repo record back under its own repo_path -- not silently relocate
        # it to the current root.
        mine = self._seed("mine", [{"raw": "m", "manual": True}])
        foreign = self.mint()
        conn = sqlite3.connect(str(self._db_dir / "sqlite.db"))
        try:
            conn.execute(
                "UPDATE tickets SET repo_path = ? WHERE id = ?",
                ("github.com/elsewhere/other", foreign),
            )
            conn.commit()
        finally:
            conn.close()
        proc = self.todo("tag-clear", "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        conn = sqlite3.connect(str(self._db_dir / "sqlite.db"))
        try:
            repos = dict(
                conn.execute("SELECT id, repo_path FROM tickets").fetchall()
            )
        finally:
            conn.close()
        self.assertEqual(repos[foreign], "github.com/elsewhere/other")
        self.assertNotEqual(repos[mine], "github.com/elsewhere/other")
        self.assertEqual(self._tags_of(mine), [])

    def test_clearing_a_tag_drops_its_stored_vectors(self) -> None:
        # Tag vectors are keyed by POSITIONAL field_path (Tag.<i>.raw), so a
        # cleared element must not leave its vector behind for whatever element
        # shifts into that index.
        tid = self._seed("vec", [{"raw": "gizmo-widget", "manual": True}])
        search = self.todo("search", "gizmo-widget", "--embedder", "apple")
        self.assertEqual(search.returncode, 0, search.stderr)
        conn = sqlite3.connect(str(self._db_dir / "sqlite.db"))
        try:
            rows = conn.execute(
                "SELECT field_path FROM embeddings WHERE ticket_id = ?", (tid,)
            ).fetchall()
        finally:
            conn.close()
        self.assertIn(("Tag.0.raw",), rows)
        proc = self.todo("tag-clear", tid[:8], "--all")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        conn = sqlite3.connect(str(self._db_dir / "sqlite.db"))
        try:
            after = conn.execute(
                "SELECT field_path FROM embeddings WHERE ticket_id = ?", (tid,)
            ).fetchall()
        finally:
            conn.close()
        self.assertNotIn(("Tag.0.raw",), after)


class DoctorAutoTagRecomputeTests(TodoCase):
    """doctor's auto-tagging is dormant (no cheap embedder); it still trusts and keeps tags."""

    def test_doctor_adds_no_automatic_tags_while_dormant(self) -> None:
        # Auto-tagging ran on the lexical `hash` embedder, which made the tags
        # md5-collision noise rather than topics; with that backend retired
        # cheap_embedders() is empty and _recompute_auto_tags stands down. It
        # re-arms on its own once a cheap SEMANTIC backend is registered (ticket
        # 91e28fd0). Manual tags must survive the dormant pass untouched.
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-a",
            tid,
            summary="alpha widgets. beta gadgets. gamma sprockets.",
            extra={"Tag": [{"raw": "manual keep", "manual": True}]},
        )
        proc = self.todo("doctor", tid[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["auto_tags"], 0)
        ticket = self.read_cur()
        self.assertEqual(_raws(ticket), ["manual keep"])
        self.assertEqual([e for e in ticket["Tag"] if e["manual"] is False], [])

    def test_doctor_trusts_existing_automatic_tags(self) -> None:
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-a",
            tid,
            summary="alpha widgets. beta gadgets. gamma sprockets.",
            extra={"Tag": [{"raw": "already there", "manual": False}]},
        )
        proc = self.todo("doctor", tid[:8])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["auto_tags"], 0)  # trusted as-is, not recomputed
        self.assertEqual(_raws(self.read_cur()), ["already there"])

    def test_doctor_dry_run_does_not_persist_auto_tags(self) -> None:
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-a", tid, summary="alpha widgets. beta gadgets. gamma sprockets."
        )
        proc = self.todo("doctor", tid[:8], "--dry-run")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Tag", self.read_cur())


class SetTagPluralShapeTests(TodoCase):
    """set --tag/--untag write the plural Tag field; search --tag matches any element."""

    def test_set_tag_writes_a_manual_plural_tag_element(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="x")
        proc = self.todo("set", self.tid, "--tag", "Billing")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ticket = self.read_cur()
        self.assertEqual(_raws(ticket), ["billing"])  # downcased, like tagadd
        self.assertTrue(ticket["Tag"][0]["manual"])

    def test_set_untag_leaves_an_automatic_tag_of_the_same_name(self) -> None:
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-a",
            tid,
            summary="x",
            extra={"Tag": [{"raw": "shared", "manual": False}]},
        )
        proc = self.todo("set", self.tid, "--untag", "shared")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("shared", _raws(self.read_cur()))  # automatic: not set's to remove

    def test_search_tag_matches_an_automatic_element_case_insensitively(self) -> None:
        tagged = self.mint()
        self.write_ticket(
            f"{tagged[:8]}-a",
            tagged,
            summary="alpha beta gamma",
            extra={"Tag": [{"raw": "ui", "manual": False}]},
        )
        untagged = self.mint()
        self.write_ticket(f"{untagged[:8]}-b", untagged, summary="alpha beta gamma")
        proc = self.todo(
            "search", "alpha beta gamma", "--embedder", "apple", "--tag", "UI"
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(tagged[:8], proc.stdout)
        self.assertNotIn(untagged[:8], proc.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
