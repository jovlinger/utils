#!/usr/bin/env python3
"""Deprecated alias for ``ingest-rename --dry-run`` (print only, no writes)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_CLI = Path(__file__).resolve().parent / "ingest-rename.py"
_SPEC = importlib.util.spec_from_file_location("ingest_rename_cli", _CLI)
assert _SPEC is not None and _SPEC.loader is not None
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)
raise SystemExit(_MOD.main(["--dry-run", *sys.argv[1:]]))
