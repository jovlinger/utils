"""Frozen acceptance for ee1799aa: the plural, provenance-tracked Tag field.

FROZEN AC authored by the orchestrator. The implementor MUST NOT modify this
file (it is the read-only oracle). Enabled by the final WorkItem (WI7).

Contract this pins (the parts testable without a git/store/CLI context; the
write-path integration -- per-element embedding, clear-on-write, search ranking,
doctor's recompute wiring -- is proven by the implementor's own tests + review):

  * Tag is a PLURAL list; each element is {"raw": <downcased str>,
    "manual": <bool>, and (once embedded) per-embedder vectors}.
  * todo_db.SCHEMA_VERSION == 7 and todo_db.RECORD_MIGRATIONS[7] converts a
    legacy flat `Tags` list-of-strings into plural `Tag` elements (manual=True,
    downcased, deduped), dropping the old `Tags` key. Reached via migrate_record.
  * todo.apply_tag_add(todo, *tags) / todo.apply_tag_remove(todo, *tags) mutate
    the MANUAL tag set in place: downcased, deduped, elements carry manual=True,
    and the whole `Tag` field is dropped when it becomes empty. apply_tag_remove
    only removes MANUAL elements (automatic tags are doctor's to manage).
  * todo.tag_findings(todo) -> list[str]: empty for a well-formed Tag, non-empty
    for a malformed one (wired into doctor).
  * todo.compute_auto_tags(text, candidates, embedder, k) -> list of AUTOMATIC
    elements ({raw in candidates, manual: False}), the top-k candidates by cosine
    similarity to text -- the ported ef4ad78d scoring, adapted to emit elements.
"""

from __future__ import annotations

import json
import unittest

import fake_nlce
import todo
import todo_db


def _raws(todo_dict) -> list:
    return [e["raw"] for e in todo_dict.get("Tag", [])]


class PluralTagEndTest(unittest.TestCase):
    def test_schema_bumped_to_7(self) -> None:
        # The plural-Tag migration is registered at v7; SCHEMA_VERSION may be
        # higher (later migrations, e.g. the v8 state renames, build on top).
        self.assertGreaterEqual(todo_db.SCHEMA_VERSION, 7)
        self.assertIn(7, todo_db.RECORD_MIGRATIONS)

    def test_migration_flat_tags_to_plural(self) -> None:
        rec = {
            "Id": "a" * 64, "Branch": "aaaaaaaa-x", "State": {"init": {}},
            "Summary": {"raw": "s"}, "Tags": ["Todo Tool", "baz", "BAZ"],
        }
        out = todo_db.migrate_record(rec)
        self.assertNotIn("Tags", out)
        self.assertEqual(out.get("_schema"), todo_db.SCHEMA_VERSION)
        # downcased + deduped, all manual
        self.assertEqual(sorted(_raws(out)), ["baz", "todo tool"])
        self.assertTrue(all(e["manual"] is True for e in out["Tag"]))

    def test_tagadd_downcased_deduped_manual(self) -> None:
        d = {"Summary": {"raw": "s"}}
        todo.apply_tag_add(d, "Todo Tool")
        todo.apply_tag_add(d, "todo tool")  # dedup no-op (already present, downcased)
        todo.apply_tag_add(d, "Embeddings")
        self.assertEqual(sorted(_raws(d)), ["embeddings", "todo tool"])
        self.assertTrue(all(e["manual"] is True for e in d["Tag"]))

    def test_tagrm_removes_manual_and_drops_empty_field(self) -> None:
        d = {"Summary": {"raw": "s"}}
        todo.apply_tag_add(d, "one", "two")
        todo.apply_tag_remove(d, "One")  # case-insensitive match
        self.assertEqual(_raws(d), ["two"])
        todo.apply_tag_remove(d, "two")
        self.assertNotIn("Tag", d)  # optional field absent, not []

    def test_tagrm_leaves_automatic_tags(self) -> None:
        d = {"Tag": [
            {"raw": "manual one", "manual": True},
            {"raw": "auto one", "manual": False},
        ]}
        todo.apply_tag_remove(d, "auto one")  # not a manual element
        self.assertIn("auto one", _raws(d))

    def test_doctor_tag_findings(self) -> None:
        good = {"Tag": [{"raw": "ok", "manual": True}]}
        self.assertEqual(todo.tag_findings(good), [])
        for bad in ({"Tag": "notalist"},
                    {"Tag": [{"manual": True}]},          # missing raw
                    {"Tag": [{"raw": 5, "manual": True}]},  # raw not str
                    {"Tag": [{"raw": "x"}]}):             # missing manual
            self.assertTrue(todo.tag_findings(bad), f"expected a finding for {bad}")

    def test_compute_auto_tags_top_k(self) -> None:
        # Was get_embedder("hash"); that lexical backend was retired, so this
        # borrows the equivalent bag-of-words test double. Contract unchanged.
        embedder = fake_nlce.BowEmbedder()
        candidates = ["alpha beta", "gamma", "delta epsilon", "zeta"]
        text = "alpha beta gamma"
        elems = todo.compute_auto_tags(text, candidates, embedder, 2)
        self.assertEqual(len(elems), 2)
        self.assertTrue(all(e["manual"] is False for e in elems))
        self.assertTrue(all(e["raw"] in candidates for e in elems))


if __name__ == "__main__":
    unittest.main()
