#!/usr/bin/env python3
"""CLI tests for `todo.py search`: time filters, the embedder switch, id pins, stopwords.

The in-process unit tests of todo_search and the query parser live in
test_todo_common.py; the black-box acceptance walk lives in
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
from test_todo import TodoCase  # noqa: E402  (temp-repo + subprocess harness)


class SearchTimeFilterTest(TodoCase):
    """Time operators AND with text search and filter create/update_dt."""

    def test_tc_after_date_only_filters_by_create_dt(self) -> None:
        old_id = self.mint()
        new_id = self.mint()
        self.write_ticket(
            f"{old_id[:8]}-o",
            old_id,
            summary="old widget",
            extra={
                "create_dt": "2026-08-24T12:00:00Z",
                "update_dt": "2026-08-24T12:00:00Z",
            },
        )
        self.write_ticket(
            f"{new_id[:8]}-n",
            new_id,
            summary="new widget",
            extra={
                "create_dt": "2026-08-25T12:00:00Z",
                "update_dt": "2026-08-25T12:00:00Z",
            },
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
            extra={
                "create_dt": "2026-01-01T00:00:00Z",
                "update_dt": "2026-01-01T00:00:00Z",
            },
        )
        self.write_ticket(
            f"{new_id[:8]}-n",
            new_id,
            summary="new widget",
            extra={
                "create_dt": "2026-06-01T00:00:00Z",
                "update_dt": "2026-06-01T00:00:00Z",
            },
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
            extra={
                "create_dt": "2026-06-01T00:00:00Z",
                "update_dt": "2026-06-01T00:00:00Z",
            },
        )
        self.write_ticket(
            f"{out_id[:8]}-o",
            out_id,
            summary="outside",
            extra={
                "create_dt": "2026-01-01T00:00:00Z",
                "update_dt": "2026-01-01T00:00:00Z",
            },
        )
        proc = self.todo(
            "search", "tc_after:2026-03-01T00:00:00Z", "--embedder", "apple"
        )
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
        self.write_ticket(
            f"{target[:8]}-target", target, summary="zzz unrelated summary text"
        )
        for n in range(3):
            filler = f"1234000{n}" + "0" * 56
            self.write_ticket(
                f"{filler[:8]}-filler{n}", filler, summary="widget maintenance"
            )
        proc = self.todo("search", "cafefeed")
        self.assertEqual(0, proc.returncode, proc.stderr)
        first_line = proc.stdout.strip().splitlines()[0]
        self.assertIn(
            "cafefeed", first_line, f"expected id hit pinned first:\n{proc.stdout}"
        )

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
        self.assertEqual(
            before, self._vectors(), "re-derive should restore the vectors"
        )

    def test_clear_strips_vectors_stamped_into_the_ticket_json(self) -> None:
        # The index is not the only copy -- vectors are stamped into the record
        # too, and a clear that missed those would leave search re-reading them.
        tid = self._seed(1)
        self._search()
        record = json.loads(self.todo("read", tid).stdout)
        self.assertTrue(
            [k for k in record["Summary"] if k != "raw"], "expected stamped vectors"
        )
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
