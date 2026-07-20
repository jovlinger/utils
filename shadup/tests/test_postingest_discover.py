"""Tests for postingest nested-album discovery (homogeneous vs heterogeneous)."""

from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

POSTINGEST_PATH = Path(__file__).resolve().parent.parent / "postingest"


def _load_postingest():
    # postingest has no .py suffix; need SourceFileLoader.
    name = "postingest"
    loader = SourceFileLoader(name, str(POSTINGEST_PATH))
    spec = importlib.util.spec_from_loader(name, loader)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod



@pytest.fixture(scope="module")
def pi():
    return _load_postingest()


def _touch_flac(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"fLaC")


def test_is_disc_like_dirname(pi) -> None:
    assert pi.is_disc_like_dirname("CD1")
    assert pi.is_disc_like_dirname("CD 02")
    assert pi.is_disc_like_dirname("Disc 1")
    assert pi.is_disc_like_dirname("disc A")
    assert pi.is_disc_like_dirname("Vol. 01")
    assert pi.is_disc_like_dirname(
        "David Bowie - Bowie at the Beeb Disc 1- The Best of the BBC"
    )
    assert not pi.is_disc_like_dirname(
        "The Doors - 1967 - Strange Days [2013 US Analogue Productions]"
    )
    assert not pi.is_disc_like_dirname("Sagajazz 44 VA - Jazz à la gitane")


def test_discover_homogeneous_vol_dirs_woodstock_style(
    tmp_path: Path, pi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Woodstock-style Vol. 01…NN is homogeneous multi-disc (parent union)."""
    files = tmp_path / "files"
    box = files / "The Woodstock & Flower Power Generation (10 Disc's)"
    for n in (1, 2, 3):
        _touch_flac(box / f"Vol. {n:02d}" / "01.flac")
    monkeypatch.setattr(pi, "FILES_ROOT", files)

    audio, parent_map = pi.discover_units([box])
    assert {p.name for p in audio} == {"Vol. 01", "Vol. 02", "Vol. 03"}
    assert box.resolve() in parent_map
    assert len(parent_map[box.resolve()]) == 3


def test_discover_homogeneous_multidisc_gets_parent_union(
    tmp_path: Path, pi, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = tmp_path / "files"
    box = files / "Cafe Del Mar - 25th Anniversary"
    for disc in ("CD1", "CD2", "CD3"):
        _touch_flac(box / disc / "01.flac")
    monkeypatch.setattr(pi, "FILES_ROOT", files)

    audio, parent_map = pi.discover_units([box])
    assert {p.name for p in audio} == {"CD1", "CD2", "CD3"}
    assert box.resolve() in parent_map
    assert {c.name for c in parent_map[box.resolve()]} == {"CD1", "CD2", "CD3"}


def test_discover_heterogeneous_box_skips_parent_union(
    tmp_path: Path, pi, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = tmp_path / "files"
    box = files / "The Doors - Infinite"
    albums = [
        "The Doors - 1967 - The Doors",
        "The Doors - 1967 - Strange Days",
        "The Doors - 1968 - Waiting For The Sun",
    ]
    for name in albums:
        _touch_flac(box / name / "01.flac")
    monkeypatch.setattr(pi, "FILES_ROOT", files)

    audio, parent_map = pi.discover_units([box])
    assert {p.name for p in audio} == set(albums)
    assert parent_map == {}


def test_discover_flat_compilation_is_single_unit(
    tmp_path: Path, pi, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = tmp_path / "files"
    comp = files / "Hi-Res Masters - 2000s"
    _touch_flac(comp / "01. Track.flac")
    _touch_flac(comp / "02. Track.flac")
    monkeypatch.setattr(pi, "FILES_ROOT", files)

    audio, parent_map = pi.discover_units([comp])
    assert [p.resolve() for p in audio] == [comp.resolve()]
    assert parent_map == {}


def test_process_parent_union_scans_collection_then_unions(
    tmp_path: Path, pi, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Homogeneous parent: musicscan collection + union children (Café both)."""
    files = tmp_path / "files"
    box = files / "Woodstock Box"
    vols = []
    for n in (1, 2):
        vol = box / f"Vol. {n:02d}"
        _touch_flac(vol / "01.flac")
        (vol / ".meta.combined.json").write_text(
            '{"schema":1,"tags":["genre;rock"],"kind":"providers"}\n',
            encoding="utf-8",
        )
        vols.append(vol)

    calls: list[list[str]] = []

    def fake_run(cmd, *args, **kwargs):
        calls.append([str(c) for c in cmd])
        return None

    monkeypatch.setattr(pi, "run", fake_run)
    monkeypatch.setattr(pi, "MUSICSCAN", Path("/fake/musicscan"))
    syn = tmp_path / "syn"
    syn.mkdir()

    assert pi.process_parent_union(
        box,
        vols,
        providers=["musicbrainz"],
        force=True,
        dry_run=False,
        include_raw=False,
        verbose=0,
        synonyms_dir=syn,
    )
    assert calls and calls[0][0] == "/fake/musicscan"
    assert str(box) in calls[0]
    combined = box / ".meta.combined.json"
    assert combined.is_file()
    import json

    doc = json.loads(combined.read_text(encoding="utf-8"))
    assert doc["kind"] == "providers+union-children"
    assert "genre;rock" in doc["tags"]
