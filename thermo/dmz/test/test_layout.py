"""Sanity checks for container layout (no Docker required)."""

from __future__ import annotations

from pathlib import Path
from unittest import TestCase


class DMZLayoutTest(TestCase):
    def setUp(self) -> None:
        self.dmz_dir = Path(__file__).resolve().parent.parent

    def test_start_sh_invokes_su_exec_and_run_sh(self) -> None:
        p = self.dmz_dir / "start.sh"
        self.assertTrue(p.is_file(), msg=f"Missing {p}")
        text = p.read_text(encoding="utf-8")
        self.assertIn("su-exec dmz", text)
        self.assertIn("/app/run.sh", text)

    def test_dockerfile_non_root_and_entrypoint(self) -> None:
        p = self.dmz_dir / "Dockerfile"
        self.assertTrue(p.is_file())
        text = p.read_text(encoding="utf-8")
        self.assertIn("adduser", text)
        self.assertIn("su-exec", text)
        self.assertIn("start.sh", text)
        self.assertIn("8080", text)
        self.assertIn(".docker-import/run-with-stdout-logged.py", text)
