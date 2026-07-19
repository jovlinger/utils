#!/usr/bin/env python3
"""Unit tests for todo_db path helpers."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

import todo_db
import todo_store


def _init_git_repo(path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(
        ["git", "config", "user.email", "t@example.com"],
        cwd=path,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Tester"],
        cwd=path,
        check=True,
    )


def _touch_sqlite_db(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    db_path = directory / "sqlite.db"
    conn = sqlite3.connect(str(db_path))
    todo_db.migrate(conn)
    conn.commit()
    conn.close()
    return db_path


class TodoDirResolutionTest(unittest.TestCase):
    """resolve_todo_dir() search order and per-call caching."""

    def tearDown(self) -> None:
        todo_db.reset_todo_dir()

    def test_todo_dir_env_wins_when_db_exists(self) -> None:
        with tempfile.TemporaryDirectory() as custom, tempfile.TemporaryDirectory() as home:
            custom_path = Path(custom)
            home_path = Path(home)
            _touch_sqlite_db(custom_path / "picked")
            _touch_sqlite_db(home_path / ".todo")
            with unittest.mock.patch.dict(
                os.environ,
                {"TODO_DIR": str(custom_path / "picked"), "HOME": str(home_path)},
                clear=False,
            ):
                resolved = todo_db.resolve_todo_dir()
                self.assertEqual(resolved, (custom_path / "picked").resolve())

    def test_repo_local_preferred_over_home(self) -> None:
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as home:
            repo_path = Path(repo)
            home_path = Path(home)
            _init_git_repo(repo_path)
            _touch_sqlite_db(repo_path / ".todo")
            _touch_sqlite_db(home_path / ".todo")
            with unittest.mock.patch.dict(os.environ, {"HOME": str(home_path)}, clear=False):
                env = os.environ.copy()
                env.pop("TODO_DIR", None)
                with unittest.mock.patch.dict(os.environ, env, clear=True):
                    resolved = todo_db.resolve_todo_dir(repo_path)
                    self.assertEqual(resolved, (repo_path / ".todo").resolve())

    def test_repo_config_json_preferred_over_home_db(self) -> None:
        """File-store repos pin via config.json even after sqlite.db is removed."""
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as home:
            repo_path = Path(repo)
            home_path = Path(home)
            _init_git_repo(repo_path)
            (repo_path / ".todo").mkdir()
            (repo_path / ".todo" / "config.json").write_text(
                '{"todo_storage": "file://$TODOBASEDIR/storage"}\n',
                encoding="utf-8",
            )
            _touch_sqlite_db(home_path / ".todo")
            with unittest.mock.patch.dict(os.environ, {"HOME": str(home_path)}, clear=False):
                env = os.environ.copy()
                env.pop("TODO_DIR", None)
                with unittest.mock.patch.dict(os.environ, env, clear=True):
                    resolved = todo_db.resolve_todo_dir(repo_path)
                    self.assertEqual(resolved, (repo_path / ".todo").resolve())

    def test_repo_storage_dir_preferred_over_home_db(self) -> None:
        """A populated storage/ directory counts even before config.json exists."""
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as home:
            repo_path = Path(repo)
            home_path = Path(home)
            _init_git_repo(repo_path)
            (repo_path / ".todo" / "storage").mkdir(parents=True)
            _touch_sqlite_db(home_path / ".todo")
            with unittest.mock.patch.dict(os.environ, {"HOME": str(home_path)}, clear=False):
                env = os.environ.copy()
                env.pop("TODO_DIR", None)
                with unittest.mock.patch.dict(os.environ, env, clear=True):
                    resolved = todo_db.resolve_todo_dir(repo_path)
                    self.assertEqual(resolved, (repo_path / ".todo").resolve())

    def test_default_create_location_is_repo_local(self) -> None:
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as home:
            repo_path = Path(repo)
            home_path = Path(home)
            _init_git_repo(repo_path)
            with unittest.mock.patch.dict(os.environ, {"HOME": str(home_path)}, clear=False):
                env = os.environ.copy()
                env.pop("TODO_DIR", None)
                with unittest.mock.patch.dict(os.environ, env, clear=True):
                    resolved = todo_db.resolve_todo_dir(repo_path)
                    self.assertEqual(resolved, (repo_path / ".todo").resolve())


class RepoIdentityMigrationTest(unittest.TestCase):
    """repo_identity_from_url() and the v3 repo_path normalization migration."""

    def test_url_shapes_canonicalize(self) -> None:
        self.assertEqual(
            todo_db.repo_identity_from_url("git@github.com:jovlinger/utils.git"),
            "github.com/jovlinger/utils",
        )
        self.assertEqual(
            todo_db.repo_identity_from_url("https://github.com/jovlinger/utils"),
            "github.com/jovlinger/utils",
        )
        self.assertIsNone(todo_db.repo_identity_from_url("not a url"))
        self.assertIsNone(todo_db.repo_identity_from_url(""))

    def _v2_db_with_ticket(self, repo_path: str, scope: dict) -> sqlite3.Connection:
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        todo_db.migrate(conn)  # build current schema
        conn.execute("UPDATE schema_version SET version = 2")  # pretend pre-identity db
        tid = "a" * 64
        data = json.dumps({"Id": tid, "Branch": "b", "Scope": scope})
        conn.execute(
            "INSERT INTO tickets(id, repo_path, branch, data, update_dt) VALUES (?, ?, ?, ?, ?)",
            (tid, repo_path, "b", data, ""),
        )
        conn.commit()
        return conn

    def test_migration_rewrites_repo_path_from_git_url(self) -> None:
        conn = self._v2_db_with_ticket(
            "/Users/johan/github.com/jovlinger/utils",
            {"git_url": "git@github.com:jovlinger/utils.git"},
        )
        todo_db.migrate(conn)  # normalizes and bumps to v3
        self.assertEqual(
            conn.execute("SELECT repo_path FROM tickets").fetchone()["repo_path"],
            "github.com/jovlinger/utils",
        )
        self.assertEqual(
            conn.execute("SELECT version FROM schema_version").fetchone()["version"],
            todo_db.SCHEMA_VERSION,
        )
        conn.close()

    def test_migration_leaves_rows_without_git_url(self) -> None:
        conn = self._v2_db_with_ticket("localname", {})
        todo_db.migrate(conn)
        self.assertEqual(
            conn.execute("SELECT repo_path FROM tickets").fetchone()["repo_path"], "localname"
        )
        conn.close()


class JsonDirStoreTest(unittest.TestCase):
    """The JSON-directory backend of the storage DAL."""

    def tearDown(self) -> None:
        todo_store.reset_store()
        todo_db.reset_todo_dir()

    def test_put_get_find_list_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = todo_store.JsonDirTodoStore(Path(d))
            todo = {
                "Id": "a" * 64,
                "Branch": "br",
                "Summary": {"raw": "hi"},
                "Scope": {"path_to_project": "/x"},
            }
            store.put("github.com/o/n", "br", todo)
            self.assertTrue((Path(d) / ("a" * 64 + ".json")).is_file())
            self.assertEqual(store.get("github.com/o/n", "br")["Id"], "a" * 64)
            self.assertIsNone(store.get("github.com/o/n", "missing"))
            found = store.find_by_id_prefix("aaaa")
            self.assertEqual(len(found), 1)
            self.assertEqual(found[0][1], "br")  # branch
            self.assertEqual([t["Id"] for t in store.list_all()], ["a" * 64])

    def test_vector_index_flags(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(todo_store.JsonDirTodoStore(Path(d)).has_vector_index)
        self.assertTrue(todo_store.SqliteTodoStore().has_vector_index)

    def test_get_store_selects_backend_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "config.json").write_text(
                json.dumps({"todo_storage": "file://$TODOBASEDIR/storage"}),
                encoding="utf-8",
            )
            with unittest.mock.patch.object(todo_db, "todo_dir", return_value=Path(d)):
                todo_store.reset_store()
                store = todo_store.get_store()
                self.assertIsInstance(store, todo_store.JsonDirTodoStore)
                self.assertEqual(store.dir, Path(d) / "storage")
        with tempfile.TemporaryDirectory() as d2:  # no config.json -> write sqlite default
            base = Path(d2)
            with unittest.mock.patch.object(todo_db, "todo_dir", return_value=base):
                todo_store.reset_store()
                self.assertIsInstance(todo_store.get_store(), todo_store.SqliteTodoStore)
                written = json.loads((base / "config.json").read_text(encoding="utf-8"))
                self.assertEqual(
                    written["todo_storage"], "sqlite://$TODOBASEDIR/sqlite.db"
                )

    def test_cached_for_subsequent_calls(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_path = Path(first)
            second_path = Path(second)
            _touch_sqlite_db(first_path)
            _touch_sqlite_db(second_path)
            with unittest.mock.patch.dict(os.environ, {"TODO_DIR": str(first_path)}, clear=False):
                self.assertEqual(todo_db.resolve_todo_dir(), first_path.resolve())
                with unittest.mock.patch.dict(
                    os.environ, {"TODO_DIR": str(second_path)}, clear=False
                ):
                    self.assertEqual(todo_db.resolve_todo_dir(), first_path.resolve())

    def test_derived_paths_share_resolved_dir(self) -> None:
        with tempfile.TemporaryDirectory() as custom:
            custom_path = Path(custom)
            with unittest.mock.patch.dict(os.environ, {"TODO_DIR": str(custom_path)}, clear=False):
                todo_db.reset_todo_dir()
                base = todo_db.todo_dir()
                self.assertEqual(todo_db.db_path(), base / "sqlite.db")
                self.assertEqual(todo_db.worktrees_dir(), base / "worktrees")


class TodoStorageDsnTest(unittest.TestCase):
    """The todo_storage DSN in config.json and its back-compat fallbacks."""

    def tearDown(self) -> None:
        todo_store.reset_store()
        todo_db.reset_todo_dir()

    def _store_for_config(self, base: Path, config: dict) -> todo_store.TodoStore:
        (base / "config.json").write_text(json.dumps(config), encoding="utf-8")
        with unittest.mock.patch.object(todo_db, "todo_dir", return_value=base):
            todo_store.reset_store()
            return todo_store.get_store()

    def test_sqlite_dsn_substitutes_todobasedir(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            store = self._store_for_config(
                base, {"todo_storage": "sqlite://$TODOBASEDIR/sqlite.db"}
            )
            self.assertIsInstance(store, todo_store.SqliteTodoStore)
            self.assertEqual(store.db_path, base / "sqlite.db")

    def test_file_dsn_substitutes_braced_todobasedir(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            store = self._store_for_config(
                base, {"todo_storage": "file://${TODOBASEDIR}/tickets"}
            )
            self.assertIsInstance(store, todo_store.JsonDirTodoStore)
            self.assertEqual(store.dir, base / "tickets")

    def test_dsn_takes_precedence_over_legacy_store_key(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            store = self._store_for_config(
                base, {"todo_storage": "file://$TODOBASEDIR/t", "store": "sqlite"}
            )
            self.assertIsInstance(store, todo_store.JsonDirTodoStore)

    def test_legacy_keys_migrated_to_dsn(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            store = self._store_for_config(base, {"store": "json"})
            self.assertIsInstance(store, todo_store.JsonDirTodoStore)
            self.assertEqual(store.dir, base / "tickets")
            written = json.loads((base / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(written["todo_storage"], "file://$TODOBASEDIR/tickets")
            self.assertNotIn("store", written)

    def test_layout_infers_storage_dir_when_no_config(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            (base / "storage").mkdir()
            with unittest.mock.patch.object(todo_db, "todo_dir", return_value=base):
                todo_store.reset_store()
                store = todo_store.get_store()
            self.assertIsInstance(store, todo_store.JsonDirTodoStore)
            self.assertEqual(store.dir, base / "storage")
            written = json.loads((base / "config.json").read_text(encoding="utf-8"))
            self.assertEqual(written["todo_storage"], "file://$TODOBASEDIR/storage")

    def test_layout_prefers_sqlite_db_over_storage_dir(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            _touch_sqlite_db(base)
            (base / "storage").mkdir()
            with unittest.mock.patch.object(todo_db, "todo_dir", return_value=base):
                todo_store.reset_store()
                store = todo_store.get_store()
            self.assertIsInstance(store, todo_store.SqliteTodoStore)
            self.assertEqual(store.db_path, base / "sqlite.db")

    def test_config_file_dsn_ignores_sibling_sqlite_db(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            _touch_sqlite_db(base)
            (base / "storage").mkdir()
            store = self._store_for_config(
                base, {"todo_storage": "file://$TODOBASEDIR/storage"}
            )
            self.assertIsInstance(store, todo_store.JsonDirTodoStore)
            self.assertEqual(store.dir, base / "storage")

    def test_lock_timings_read_from_config(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            base = Path(d)
            store = self._store_for_config(
                base,
                {"todo_storage": "sqlite://$TODOBASEDIR/sqlite.db", "lock_grace": 3, "lock_ttl": 2},
            )
            self.assertEqual((store._grace, store._ttl), (3.0, 2.0))

    def test_bad_dsn_shapes_raise(self) -> None:
        for bad in ("no-scheme-here", "mysql://whatever"):
            with tempfile.TemporaryDirectory() as d:
                base = Path(d)
                with self.assertRaises(todo_store.TodoStoreError):
                    self._store_for_config(base, {"todo_storage": bad})


class PerTodoLockTest(unittest.TestCase):
    """Per-TODO advisory locking on both backends."""

    TID = "a" * 64
    OTHER_TID = "b" * 64
    FOREIGN_PID = 2147480000  # a pid this test process cannot be

    def tearDown(self) -> None:
        todo_store.reset_store()
        todo_db.reset_todo_dir()

    # -- sqlite backend ----------------------------------------------------

    def _sqlite_store(self, base: Path, **kw: float) -> todo_store.SqliteTodoStore:
        return todo_store.SqliteTodoStore(db_path=base / "sqlite.db", grace=0.3, ttl=100.0, **kw)

    def _sqlite_insert_lock(self, db: Path, ticket_id: str, expires_at: float) -> None:
        with todo_db.connection(db) as conn:
            conn.execute(
                "INSERT INTO locks(ticket_id, pid, expires_at) VALUES (?, ?, ?)",
                (ticket_id, self.FOREIGN_PID, expires_at),
            )

    def test_sqlite_lock_roundtrip_and_ownership(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._sqlite_store(Path(d))
            db = store.db_path
            with store.lock(self.TID):
                row = None
                with todo_db.connection(db) as conn:
                    row = conn.execute(
                        "SELECT pid FROM locks WHERE ticket_id = ?", (self.TID,)
                    ).fetchone()
                self.assertEqual(int(row["pid"]), os.getpid())
            with todo_db.connection(db) as conn:  # released on exit
                self.assertIsNone(
                    conn.execute(
                        "SELECT 1 FROM locks WHERE ticket_id = ?", (self.TID,)
                    ).fetchone()
                )

    def test_sqlite_foreign_holder_blocks_then_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._sqlite_store(Path(d))
            self._sqlite_insert_lock(store.db_path, self.TID, time.time() + 100)
            self.assertFalse(store._try_acquire(self.TID, 100.0))
            with self.assertRaises(todo_store.LockTimeout):
                with store.lock(self.TID):
                    pass

    def test_sqlite_expired_lock_is_stolen(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._sqlite_store(Path(d))
            self._sqlite_insert_lock(store.db_path, self.TID, time.time() - 1)
            with store.lock(self.TID):  # steals the dead holder's lock
                pass

    def test_sqlite_force_unlock_all(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._sqlite_store(Path(d))
            self._sqlite_insert_lock(store.db_path, self.TID, time.time() + 100)
            self._sqlite_insert_lock(store.db_path, self.OTHER_TID, time.time() + 100)
            self.assertEqual(store.force_unlock_all(), 2)
            self.assertTrue(store._try_acquire(self.TID, 100.0))

    # -- file backend ------------------------------------------------------

    def _file_store(self, base: Path) -> todo_store.JsonDirTodoStore:
        return todo_store.JsonDirTodoStore(base, grace=0.3, ttl=100.0)

    def test_file_lock_exclusion_and_release(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._file_store(Path(d))
            self.assertTrue(store._try_acquire(self.TID, 100.0))
            self.assertFalse(store._try_acquire(self.TID, 100.0))  # already held
            store._release(self.TID)
            self.assertTrue(store._try_acquire(self.TID, 100.0))  # free again
            store._release(self.TID)

    def test_file_foreign_holder_times_out_then_steals_when_expired(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._file_store(Path(d))
            lock_path = store._lock_path(self.TID)
            lock_path.write_text(f"{self.FOREIGN_PID} {time.time() + 100}", encoding="ascii")
            with self.assertRaises(todo_store.LockTimeout):
                with store.lock(self.TID):
                    pass
            lock_path.write_text(f"{self.FOREIGN_PID} {time.time() - 1}", encoding="ascii")
            with store.lock(self.TID):  # expired -> stolen
                pass

    def test_file_force_unlock_all(self) -> None:
        with tempfile.TemporaryDirectory() as d:
            store = self._file_store(Path(d))
            store._try_acquire(self.TID, 100.0)
            store._try_acquire(self.OTHER_TID, 100.0)
            self.assertEqual(store.force_unlock_all(), 2)


if __name__ == "__main__":
    unittest.main()
