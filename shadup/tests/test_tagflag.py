"""tagflag argv mapping onto postingest."""

from __future__ import annotations

import importlib.machinery
import importlib.util
from pathlib import Path

TAGFLAG_PY = Path(__file__).resolve().parent.parent / "tagflag.py"


def _load() -> object:
    loader = importlib.machinery.SourceFileLoader("tagflag_mod", str(TAGFLAG_PY))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_build_postingest_argv_force_and_roots() -> None:
    mod = _load()
    argv = mod.build_postingest_argv(
        [Path("/tmp/a"), Path("/tmp/b")],
        force=True,
        dry_run=False,
        verbose=2,
        extra=[],
    )
    assert argv[:2] == ["--force_provider", "--force_retag"]
    assert "-vv" in argv
    assert argv[-2:] == ["/tmp/a", "/tmp/b"]


def test_build_postingest_argv_default_no_force() -> None:
    mod = _load()
    argv = mod.build_postingest_argv(
        [],
        force=False,
        dry_run=True,
        verbose=0,
        extra=["--skip-refresh"],
    )
    assert "--force_provider" not in argv
    assert argv[0] == "--dry-run"
    assert "--skip-refresh" in argv


def test_find_postingest_sibling() -> None:
    mod = _load()
    found = mod.find_postingest()
    assert found.name == "postingest"
    assert found.is_file()
