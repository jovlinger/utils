"""Tests for object-store path detection when ``--shadir`` is a broad prefix."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "shadup", Path(__file__).resolve().parent.parent / "shadup.py"
)
assert _SPEC and _SPEC.loader
_MOD = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MOD)


def test_library_under_files_not_considered_sha_store() -> None:
    """``files/…`` under a broad flac shadir must still be walked."""
    t = _MOD.is_under_sha_store_tree
    assert not t("/mnt/music/flac/files/Album/a.flac", "/mnt/music/flac")


def test_hex_bucket_considered_sha_store() -> None:
    """Legacy flat ``shadir/f1/…`` (no ``data/`` prefix)."""
    t = _MOD.is_under_sha_store_tree
    assert t("/mnt/music/flac/f1/ab12cd", "/mnt/music/flac")


def test_data_prefix_buckets_are_sha_store() -> None:
    t = _MOD.is_under_sha_store_tree
    assert t("/mnt/music/flac/data/f1/ab12cd", "/mnt/music/flac")


def test_dot_shadir_under_shadir_prefix() -> None:
    t = _MOD.is_under_sha_store_tree
    assert t("/mnt/music/flac/.shadir/x", "/mnt/music/flac")


def test_path_outside_shadir_false() -> None:
    t = _MOD.is_under_sha_store_tree
    assert not t("/other/flac/files/a", "/mnt/music/flac")
