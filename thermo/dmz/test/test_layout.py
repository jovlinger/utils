"""Sanity checks for container layout (no Docker required)."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def dmz_dir() -> Path:
    return Path(__file__).resolve().parent.parent


def test_start_sh_invokes_su_exec_and_run_sh(dmz_dir: Path) -> None:
    p = dmz_dir / "start.sh"
    assert p.is_file(), f"Missing {p}"
    text = p.read_text(encoding="utf-8")
    assert "su-exec dmz" in text
    assert "/app/run.sh" in text


def test_dockerfile_non_root_and_entrypoint(dmz_dir: Path) -> None:
    p = dmz_dir / "Dockerfile"
    assert p.is_file()
    text = p.read_text(encoding="utf-8")
    assert "adduser" in text
    assert "su-exec" in text
    assert "start.sh" in text
    assert "8080" in text
    assert ".docker-import/run-with-stdout-logged.py" in text
