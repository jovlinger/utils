#!/usr/bin/env python3
"""Implementor tests for the plural, provenance-tracked Tag field (ee1799aa).

Covers what test_todo_tag.py (the frozen oracle) leaves to the implementor:
per-element embedding on write, clear-on-write when a tag's raw changes, and
search ranking picking up a Tag match. Also carries extra unit coverage for
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

import todo
import todo_db

from test_todo import TODO_PY, TodoCase


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
    """End-to-end: tagadd stamps per-element vectors; edits clear them; search ranks by tag."""

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

    def test_tagadd_stamps_cheap_vector_for_that_element(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="x")
        proc = self.todo("tagadd", "Billing")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        ticket = self.read_self()
        self.assertEqual(ticket["Tag"][0]["raw"], "billing")
        self.assertIn("hash", ticket["Tag"][0])  # cheap embedder stamped inline
        self.assertIn((tid, "Tag.0.raw", "hash"), self._emb_rows())

    def test_two_tags_get_independent_field_paths(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="x")
        proc = self.todo("tagadd", "alpha", "beta")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = {(field, emb) for _t, field, emb in self._emb_rows()}
        self.assertIn(("Tag.0.raw", "hash"), rows)
        self.assertIn(("Tag.1.raw", "hash"), rows)

    def test_editing_a_tags_raw_clears_only_that_elements_vectors(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="x")
        proc = self.todo("tagadd", "alpha", "beta")
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
        proc = self._set_json_path("self", "Tag.0.raw", stdin='"gamma"')
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rows = self._emb_rows()
        tag0_embedders = {emb for _t, field, emb in rows if field == "Tag.0.raw"}
        tag1_embedders = {emb for _t, field, emb in rows if field == "Tag.1.raw"}
        self.assertNotIn(stale, tag0_embedders)  # cleared: this element's raw changed
        self.assertIn("hash", tag0_embedders)  # cheap repopulated for the new text
        self.assertIn(stale, tag1_embedders)  # untouched: a different element
        # get-json-path (not read/read_self): it never merges the sqlite
        # embeddings index, so the still-injected 4-byte fake "stale" blob on
        # Tag.1.raw (never a validly packed vector -- read would try to unpack
        # it) does not need to be touched to check the raw text landed right.
        first = self.todo("get-json-path", "self", "Tag.0.raw")
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(first.stdout.strip(), "gamma")
        second = self.todo("get-json-path", "self", "Tag.1.raw")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.strip(), "beta")

    def test_search_ranks_todo_whose_tag_matches_the_query(self) -> None:
        tagged = self.mint()
        self.write_ticket(f"{tagged[:8]}-a", tagged, summary="unrelated summary text")
        proc = self.todo("tagadd", "gizmo-widget")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        untagged = self.mint()
        self.write_ticket(f"{untagged[:8]}-b", untagged, summary="also unrelated text")
        proc = self.todo("search", "gizmo-widget", "--embedder", "hash")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn(tagged[:8], proc.stdout)
        self.assertNotIn(untagged[:8], proc.stdout)

    def test_tagrm_drops_field_and_no_longer_ranks(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="unrelated summary text")
        proc = self.todo("tagadd", "unique-marker-xyz")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = self.todo("search", "unique-marker-xyz", "--embedder", "hash")
        self.assertIn(tid[:8], proc.stdout)
        proc = self.todo("tagrm", "unique-marker-xyz")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn("Tag", self.read_self())
        proc = self.todo("search", "unique-marker-xyz", "--embedder", "hash")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertNotIn(tid[:8], proc.stdout)


class TagCliRoundTripTests(TodoCase):
    """tagadd/tagrm as a black-box: idempotence, dedup, manual-only removal."""

    def test_tagadd_idempotent_and_deduped(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="x")
        self.todo("tagadd", "Todo Tool")
        self.todo("tagadd", "todo tool")
        proc = self.todo("tagadd", "Embeddings")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(sorted(_raws(self.read_self())), ["embeddings", "todo tool"])

    def test_tagrm_leaves_automatic_tag_via_cli(self) -> None:
        tid = self.mint()
        self.write_ticket(
            f"{tid[:8]}-a",
            tid,
            summary="x",
            extra={"Tag": [{"raw": "auto one", "manual": False}]},
        )
        proc = self.todo("tagrm", "auto one")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("auto one", _raws(self.read_self()))

    def test_doctor_ok_for_well_formed_tag(self) -> None:
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-a", tid, summary="x")
        self.todo("tagadd", "ok")
        proc = self.todo("doctor", "self")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue(json.loads(proc.stdout)["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
