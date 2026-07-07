#!/usr/bin/env python3
"""Unit tests for todo_db path helpers."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import tempfile
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

    def test_home_fallback_when_only_home_has_db(self) -> None:
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as home:
            repo_path = Path(repo)
            home_path = Path(home)
            _init_git_repo(repo_path)
            _touch_sqlite_db(home_path / ".todo")
            with unittest.mock.patch.dict(os.environ, {"HOME": str(home_path)}, clear=False):
                env = os.environ.copy()
                env.pop("TODO_DIR", None)
                with unittest.mock.patch.dict(os.environ, env, clear=True):
                    resolved = todo_db.resolve_todo_dir(repo_path)
                    self.assertEqual(resolved, (home_path / ".todo").resolve())

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
            conn.execute("SELECT version FROM schema_version").fetchone()["version"], 3
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
                json.dumps({"store": "json"}), encoding="utf-8"
            )
            with unittest.mock.patch.object(todo_db, "todo_dir", return_value=Path(d)):
                todo_store.reset_store()
                self.assertIsInstance(todo_store.get_store(), todo_store.JsonDirTodoStore)
        with tempfile.TemporaryDirectory() as d2:  # no config.json -> default sqlite
            with unittest.mock.patch.object(todo_db, "todo_dir", return_value=Path(d2)):
                todo_store.reset_store()
                self.assertIsInstance(todo_store.get_store(), todo_store.SqliteTodoStore)

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


if __name__ == "__main__":
    unittest.main()
