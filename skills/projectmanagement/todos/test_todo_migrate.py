"""End-to-end acceptance for 58e8: migrate-to-latest (unified schema migrator).

FROZEN AC authored by the orchestrator. The implementor MUST NOT modify this
file (it is the read-only oracle). It is skipped until the feature lands; the
final WorkItem (WI6) removes the skip once migrate-to-latest is complete.

Contract this pins (what the implementor must build):
  * todo_db.SCHEMA_VERSION -- the SINGLE schema version (table + record share it).
  * todo_db.RECORD_MIGRATIONS: dict[int, Callable[[dict], dict]] -- a record
    transform keyed by the version it produces. A version with only table work
    simply registers no record transform (a no-op on the record axis).
  * todo_db.migrate_record(todo) -> todo -- applies every RECORD_MIGRATIONS step
    with version > todo.get("_schema", 0) and <= SCHEMA_VERSION, in ascending
    version order, then stamps todo["_schema"] = SCHEMA_VERSION. Idempotent.
  * store.get_data_version() -> int / store.set_data_version(v) -- per-backend
    marker of how far the store's RECORDS have been swept (0 when unset). This
    is distinct from the sqlite table schema_version (which auto-applies on
    connect); it is the O(1) startup-check signal.
  * todo.migrate_store(store, *, dry_run=False) -> {"scanned": int,
    "migrated": int} -- table migrations (via the store), then sweep every
    record (list_located), migrate_record each, put back the changed ones, and
    set_data_version(SCHEMA_VERSION). dry_run reports counts and writes nothing.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import todo
import todo_db
import todo_store

# A pre-versioning record: no _schema, plus legacy shapes migrate_record must
# normalize (Chunks->WorkItems, Subtickets->Subtodos, singular Parent dict->list,
# Scope.path_to_project stripped).
LEGACY_RECORD = {
    "Id": "a" * 64,
    "Branch": "aaaaaaaa-legacy",
    "State": {"init": {}},
    "Scope": {
        "branch": "aaaaaaaa-legacy",
        "git_url": "https://github.com/jovlinger/utils.git",
        "path_to_project": "/old/machine/path",
    },
    "Summary": {"raw": "legacy record"},
    "Body": {"raw": "carries Chunks and a singular Parent dict"},
    "Chunks": [{"kind": "task", "summary": "old work item", "done": False}],
    "Subtickets": [],
    "Parent": {"Id": "b" * 64, "Branch": "bbbbbbbb-parent"},
}


@unittest.skip("until 58e8 migrate-to-latest lands; WI6 removes this skip")
class MigrateToLatestEndTest(unittest.TestCase):
    """migrate-to-latest brings a below-latest store to SCHEMA_VERSION on both backends."""

    def _seed(self, store) -> None:
        store.put("test/repo", LEGACY_RECORD["Branch"], json.loads(json.dumps(LEGACY_RECORD)))

    def _only_record(self, store) -> dict:
        located = store.list_located()
        self.assertEqual(len(located), 1, "expected exactly one seeded record")
        return located[0][2]

    def _assert_migrated(self, store) -> None:
        rec = self._only_record(store)
        # Legacy field-name migrations applied.
        self.assertIn("WorkItems", rec)
        self.assertNotIn("Chunks", rec)
        self.assertNotIn("Subtickets", rec)
        # Singular Parent dict -> list of refs.
        self.assertIsInstance(rec["Parent"], list)
        self.assertEqual(rec["Parent"][0]["Id"], "b" * 64)
        # Machine-specific Scope path dropped.
        self.assertNotIn("path_to_project", rec["Scope"])
        # Record stamped and store marker advanced to the single latest version.
        self.assertEqual(rec.get("_schema"), todo_db.SCHEMA_VERSION)
        self.assertEqual(store.get_data_version(), todo_db.SCHEMA_VERSION)

    def _run_backend(self, store) -> None:
        self.assertEqual(store.get_data_version(), 0, "fresh store is unversioned")
        self._seed(store)
        first = todo.migrate_store(store)
        self.assertEqual(first["scanned"], 1)
        self.assertEqual(first["migrated"], 1)
        self._assert_migrated(store)
        # Idempotent: a second sweep migrates nothing.
        second = todo.migrate_store(store)
        self.assertEqual(second["scanned"], 1)
        self.assertEqual(second["migrated"], 0)
        self._assert_migrated(store)

    def test_sqlite_backend(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self._run_backend(todo_store.SqliteTodoStore(db_path=Path(d) / "sqlite.db"))

    def test_file_dir_backend(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self._run_backend(todo_store.JsonDirTodoStore(Path(d) / "storage"))

    def test_dry_run_writes_nothing(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = todo_store.JsonDirTodoStore(Path(d) / "storage")
            self._seed(store)
            report = todo.migrate_store(store, dry_run=True)
            self.assertEqual(report["migrated"], 1)  # would migrate one
            rec = self._only_record(store)
            self.assertIn("Chunks", rec)  # but the store is untouched
            self.assertEqual(store.get_data_version(), 0)

    def test_migrate_record_idempotent(self) -> None:
        once = todo_db.migrate_record(json.loads(json.dumps(LEGACY_RECORD)))
        self.assertEqual(once.get("_schema"), todo_db.SCHEMA_VERSION)
        twice = todo_db.migrate_record(json.loads(json.dumps(once)))
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
