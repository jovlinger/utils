"""Tests for ``--refresh-extracted-tags`` mirror layout (flat per-tag symlinks).

Layout under ``<parent-of-shadir>/files``::

  ``_tags/<tag_mirror_dir_name(tag)>/<basename-or-basename(n)>`` → symlink
  to ``<root>/<dir-key>`` (logical ``tag`` is unchanged in the DB; mirror
  directory names sanitize ``:`` and other reserved characters).

* ``NOTAGS`` holds mirrors for directories whose computed tag set is empty.
* **Directory tags** = ⋃ over **direct children** (files use DB tags; subdirs use
  their computed set).
* Within each tag folder, names are disambiguated with ``(2)``, ``(3)``, … when
  the same basename appears more than once (see :func:`plan_refresh_extracted_tag_mirrors`).

The user worked example under ``test_user_abcdf_tree_mirror_plan``; one line in
their sketch was inconsistent (``z`` mirroring ``d`` while ``d/`` is ``y``-only) —
the test encodes the corrected plan.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"


def _load_shadup() -> object:
    spec = importlib.util.spec_from_file_location("shadup_mod", SHADUP_PY)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_sh = _load_shadup()
plan_refresh_extracted_tag_mirrors = _sh.plan_refresh_extracted_tag_mirrors
NOTAGS_DIR_NAME = _sh.NOTAGS_DIR_NAME
tag_mirror_dir_name = _sh.tag_mirror_dir_name


def _run_shadup(
    cwd: Path,
    shadir: Path,
    args: list[str],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    cmd = [sys.executable, str(SHADUP_PY), "--shadir", str(shadir), *args]
    return subprocess.run(
        cmd,
        cwd=cwd,
        check=check,
        capture_output=True,
        text=True,
    )


def _find_sorted_relative_to_files(files_root: Path) -> str:
    """``cd files && find _tags | sort`` (paths relative to ``files/``)."""
    r = subprocess.run(
        ["find", "_tags", "-print"],
        cwd=files_root,
        check=True,
        capture_output=True,
        text=True,
    )
    lines = sorted(p for p in r.stdout.strip().split("\n") if p)
    return "\n".join(lines) + ("\n" if lines else "")


def _depth(dir_key: str) -> int:
    return 0 if not dir_key else len(dir_key.split("/"))


def compute_dir_tags_from_file_specs(
    files_root: Path, file_specs: list[tuple[Path, list[str]]]
) -> dict[str, frozenset[str]]:
    """Directory relpath (``\"\"`` = root) → recursive-union tag set."""
    rel_pairs: list[tuple[Path, frozenset[str]]] = [
        (p.relative_to(files_root), frozenset(tags)) for p, tags in file_specs
    ]
    file_map: dict[str, frozenset[str]] = {p.as_posix(): t for p, t in rel_pairs}

    all_dirs: set[str] = {""}
    for fp in file_map:
        parent = Path(fp).parent
        while parent.as_posix() not in ("", "."):
            all_dirs.add(parent.as_posix())
            parent = parent.parent
        all_dirs.add("")

    def direct_files(d: str) -> list[str]:
        out: list[str] = []
        for fp in file_map:
            par = Path(fp).parent.as_posix()
            if par == ".":
                par = ""
            if par == d:
                out.append(fp)
        return out

    def direct_subdirs(d: str) -> list[str]:
        prefix = f"{d}/" if d else ""
        out: list[str] = []
        for cand in all_dirs:
            if not cand or cand == d:
                continue
            if d and not cand.startswith(prefix):
                continue
            if not d:
                rest = cand
            else:
                rest = cand[len(prefix) :]
            if "/" not in rest:
                out.append(cand)
        return sorted(out)

    result: dict[str, frozenset[str]] = {}
    for d in sorted(all_dirs, key=lambda k: (-_depth(k), k)):
        acc: set[str] = set()
        for fp in direct_files(d):
            acc |= set(file_map[fp])
        for sd in direct_subdirs(d):
            acc |= set(result[sd])
        result[d] = frozenset(acc)
    return result


def _expected_find_lines_from_plan(
    files_root: Path, rows: list[tuple[str, str, str]]
) -> str:
    """Sorted ``find`` lines under ``files/_tags`` for a mirror *plan*."""
    fr = files_root.resolve()
    paths: set[str] = set()
    anchor = (fr / "_tags").resolve()

    def add_chain(p: Path) -> None:
        cur = p.resolve()
        while True:
            rel = os.path.relpath(cur, fr)
            if rel != ".":
                paths.add(rel.replace(os.sep, "/"))
            if cur == anchor:
                break
            if cur.parent == cur:
                break
            cur = cur.parent

    add_chain(fr / "_tags")
    for tag, name, _dk in rows:
        add_chain(fr / "_tags" / tag_mirror_dir_name(tag) / name)
    return "\n".join(sorted(paths)) + ("\n" if paths else "")


def _symlink_checks_from_plan(
    files_root: Path, rows: list[tuple[str, str, str]]
) -> list[tuple[Path, str]]:
    """(path relative to ``files_root``, expected readlink text)."""
    out: list[tuple[Path, str]] = []
    for tag, name, dk in rows:
        rel = Path("_tags") / tag_mirror_dir_name(tag) / name
        target = files_root / dk
        link_parent = (files_root / rel).parent
        txt = os.path.relpath(target, link_parent)
        out.append((rel, txt))
    return out


def _dir_key_from_plan_row(rel: Path, rows: list[tuple[str, str, str]]) -> str:
    """Map ``_tags/<tag_dir>/<name>`` back to dir_key using the plan."""
    assert rel.parts[0] == "_tags"
    tag_fs, name = rel.parts[1], rel.parts[2]
    for t, n, dk in rows:
        if tag_mirror_dir_name(t) == tag_fs and n == name:
            return dk
    raise AssertionError(f"no plan row for {rel}")


def test_tag_mirror_dir_name_legacy_artist_colon() -> None:
    assert tag_mirror_dir_name("artist:depechemode") == "artist;depechemode"
    assert tag_mirror_dir_name("rock") == "rock"
    assert tag_mirror_dir_name(NOTAGS_DIR_NAME) == NOTAGS_DIR_NAME
    assert tag_mirror_dir_name('a<b>c') == "a_b_c"


def test_user_abcdf_tree_mirror_plan() -> None:
    """Precomputed tag sets from the a/b/f … tree.`."""
    tags_by_dir: dict[str, frozenset[str]] = {
        "a": frozenset({"x", "y", "z"}),
        "a/b": frozenset({"x", "y"}),
        "a/a": frozenset({"x", "z"}),
        "d": frozenset({"y"}),
        "e": frozenset(),
    }
    rows = plan_refresh_extracted_tag_mirrors(tags_by_dir)
    # Order matches shadup.plan_refresh_extracted_tag_mirrors (tags x,y,z then NOTAGS).
    want: list[tuple[str, str, str]] = [
        ("x", "a", "a"),
        ("x", "b", "a/b"),
        ("x", "a(2)", "a/a"),
        ("y", "a", "a"),
        ("y", "b", "a/b"),
        ("y", "d", "d"),
        ("z", "a", "a"),
        ("z", "a(2)", "a/a"),
        (NOTAGS_DIR_NAME, "e", "e"),
    ]
    assert rows == want


def _build_three_level_two_plus_two(
    files_root: Path,
) -> list[tuple[Path, list[str]]]:
    """3 levels: levels 0–1 have 2 files + 2 dirs; level-2 dirs are leaves (2 files)."""
    spec: list[tuple[Path, list[str]]] = []

    def rel(p: Path) -> Path:
        full = files_root / p
        full.parent.mkdir(parents=True, exist_ok=True)
        return full

    rel(Path("a0.txt")).write_text("content-a0\n", encoding="utf-8")
    spec.append((rel(Path("a0.txt")), ["L0", "alpha"]))
    rel(Path("b0.txt")).write_text("content-b0\n", encoding="utf-8")
    spec.append((rel(Path("b0.txt")), ["L0", "beta"]))

    for d0 in ("d0", "d1"):
        base0 = Path(d0)
        rel(base0 / "a1.txt").write_text(f"a1-{d0}\n", encoding="utf-8")
        spec.append((rel(base0 / "a1.txt"), ["L1", "gamma", f"branch-{d0}"]))
        rel(base0 / "b1.txt").write_text(f"b1-{d0}\n", encoding="utf-8")
        spec.append((rel(base0 / "b1.txt"), ["L1", "delta"]))
        for e in ("e0", "e1"):
            base1 = base0 / e
            rel(base1 / "a2.txt").write_text(f"a2-{d0}-{e}\n", encoding="utf-8")
            spec.append(
                (rel(base1 / "a2.txt"), ["L2", "epsilon", f"branch-{d0}", f"slot-{e}"])
            )
            rel(base1 / "b2.txt").write_text(f"b2-{d0}-{e}\n", encoding="utf-8")
            spec.append((rel(base1 / "b2.txt"), ["L2", "zeta", "leaf"]))

    return spec


@pytest.fixture
def three_level_fixture(
    tmp_path: Path,
) -> tuple[Path, Path, list[tuple[Path, list[str]]]]:
    shadir = tmp_path / "blob_store"
    shadir.mkdir()
    files_root = tmp_path / "files"
    files_root.mkdir()
    spec = _build_three_level_two_plus_two(files_root)
    return shadir, files_root, spec


def test_golden_directory_tags_three_level_tree(
    three_level_fixture: tuple[Path, Path, list[tuple[Path, list[str]]]],
) -> None:
    """Recursive directory tag sets for the 3-level 2+2 fixture."""
    _s, files_root, file_specs = three_level_fixture
    tags_by_dir = compute_dir_tags_from_file_specs(files_root, file_specs)

    root = tags_by_dir[""]
    assert "L0" in root and "L1" in root and "L2" in root
    assert "alpha" in root and "leaf" in root

    assert "branch-d0" in tags_by_dir["d0"] and "branch-d1" not in tags_by_dir["d0"]
    assert "branch-d1" in tags_by_dir["d1"] and "branch-d0" not in tags_by_dir["d1"]


def test_refresh_extracted_tags_pipeline_find_and_symlinks(
    three_level_fixture: tuple[Path, Path, list[tuple[Path, list[str]]]],
) -> None:
    """Store → tag-add → extract → refresh; ``find`` + symlinks match ``plan_*``."""
    shadir, files_root, file_specs = three_level_fixture
    assert len(file_specs) == 14

    tags_by_dir = compute_dir_tags_from_file_specs(files_root, file_specs)
    rows = plan_refresh_extracted_tag_mirrors(tags_by_dir)
    want_find = _expected_find_lines_from_plan(files_root, rows)
    want_links = _symlink_checks_from_plan(files_root, rows)

    tmp_path = files_root.parent
    _run_shadup(tmp_path, shadir, ["store", "files"])

    for orig, tags in file_specs:
        assert orig.is_symlink()
        _run_shadup(tmp_path, shadir, ["tag-add", str(orig), *tags])

    _run_shadup(tmp_path, shadir, ["extract", "files"])
    _run_shadup(tmp_path, shadir, ["refresh-extracted-tags"])

    got_find = _find_sorted_relative_to_files(files_root)
    assert got_find == want_find, (
        "sorted find mismatch:\n--- expected ---\n"
        f"{want_find}\n--- actual ---\n{got_find}"
    )

    for rel, want_text in want_links:
        link = files_root / rel
        assert link.is_symlink(), f"expected symlink at {link}"
        assert (
            os.readlink(link) == want_text
        ), f"{link}: got {os.readlink(link)!r} want {want_text!r}"
    for rel, _want_text in want_links:
        link = files_root / rel
        target = (link.parent / os.readlink(link)).resolve()
        dir_key = _dir_key_from_plan_row(rel, rows)
        expect = (files_root / dir_key).resolve()
        assert target == expect, f"{link} -> {target} expected {expect}"
