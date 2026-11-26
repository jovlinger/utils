"""Test harness for todoweb: a real store and git repo per test, seeded through todo.py.

Not collected itself (no ``test_`` prefix). Every store write the setup makes
goes through ``todo.py`` as a child process, the same route todoweb uses, so a
todoweb test exercises todoweb plus the todo.py it drives and nothing else.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

import todoweb_core

HERE = Path(__file__).resolve().parent
TODO_PY = HERE / "todo.py"
TODOWEB_PY = HERE / "todoweb.py"

# Offline by default so an accidental real fetch can never reach out or prompt.
GIT_ENV = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}


class WebStoreCase(unittest.TestCase):
    """A fresh git repo and todo store per test; todo.py and todoweb run as children."""

    pytestmark = pytest.mark.e2e

    def setUp(self) -> None:
        self.repo = Path(tempfile.mkdtemp(prefix="todoweb-repo-"))
        self.store_dir = Path(tempfile.mkdtemp(prefix="todoweb-store-"))
        self.addCleanup(shutil.rmtree, self.repo, True)
        self.addCleanup(shutil.rmtree, self.store_dir, True)
        self.write_config({})
        self.env: Dict[str, str] = {**GIT_ENV, "TODO_DIR": str(self.store_dir)}
        self.git("init", "-q")
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "Tester")
        self.git("commit", "-q", "--allow-empty", "-m", "seed")

    def write_config(self, config: Dict[str, Any]) -> None:
        """Replace the store's config.json (its presence marks TODO_DIR populated)."""
        (self.store_dir / "config.json").write_text(
            json.dumps(config), encoding="utf-8"
        )

    def git(self, *args: str, cwd: Optional[Path] = None) -> str:
        """Run git in the repo (or *cwd*); return its stdout."""
        return subprocess.run(
            ["git", *args],
            cwd=cwd or self.repo,
            capture_output=True,
            text=True,
            check=True,
            env=GIT_ENV,
        ).stdout

    def todo(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run ``todo.py <args>`` in the repo against this store."""
        return subprocess.run(
            [sys.executable, str(TODO_PY), *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=False,
            env=self.env,
        )

    def seed(
        self,
        ticket_id: str,
        summary: str,
        *,
        body: str = "",
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Import one todo through `todo.py import-json`."""
        ticket: Dict[str, Any] = {
            "Id": ticket_id,
            "Branch": f"{ticket_id[:8]}-web",
            "State": {"ready": {}},
            "Summary": {"raw": summary},
        }
        if body:
            ticket["Body"] = {"raw": body}
        ticket.update(extra or {})
        seed = self.store_dir / f"seed-{ticket_id[:8]}.json"
        seed.write_text(json.dumps(ticket), encoding="utf-8")
        proc = self.todo("import-json", f"--from-json={seed}")
        seed.unlink()
        self.assertEqual(0, proc.returncode, proc.stderr)

    def stored(self, ticket_id: str) -> Dict[str, Any]:
        """The todo as `todo.py read` prints it."""
        proc = self.todo("read", ticket_id)
        self.assertEqual(0, proc.returncode, proc.stderr)
        return json.loads(proc.stdout)

    def client(self) -> todoweb_core.TodoCli:
        """The todo.py client todoweb would build in this repo, with this store's env."""
        return todoweb_core.TodoCli(self.repo, env=self.env)
