#!/usr/bin/env python3
"""Unit tests for todo_db path helpers."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import todo_db


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
