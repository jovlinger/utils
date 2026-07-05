#!/usr/bin/env python3
"""Unit tests for todo_db path helpers."""

from __future__ import annotations

import os
import unittest
import unittest.mock
from pathlib import Path

import todo_db


class WorktreesDirTest(unittest.TestCase):
    """todo_db.worktrees_dir() default and env override."""

    def test_default_is_todo_worktrees(self) -> None:
        env = os.environ.copy()
        env.pop("TODO_WORKTREES_DIR", None)
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(todo_db.worktrees_dir(), Path.home() / ".todo" / "worktrees")

    def test_env_override(self) -> None:
        with unittest.mock.patch.dict(
            os.environ, {"TODO_WORKTREES_DIR": "/tmp/custom-worktrees"}, clear=False
        ):
            self.assertEqual(todo_db.worktrees_dir(), Path("/tmp/custom-worktrees"))


if __name__ == "__main__":
    unittest.main()
