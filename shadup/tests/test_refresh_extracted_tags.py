"""Contract tests for ``--refresh-extracted-tags`` (intended behavior).

Layout (under ``<parent-of-shadir>/files``)::

  ``_tags/<tag>/<dir-relpath>`` → symlink to the mirrored directory under ``files/``

* ``<dir-relpath>`` uses POSIX components (no leading slash). The **root**
  directory uses a symlink named :data:`ROOT_LINK_NAME` under each tag, because
  ``_tags/<tag>`` must remain a real directory so paths like
  ``_tags/<tag>/d0/e0`` can exist.
* **Tags on a directory** = ⋃ over **direct children** of each child’s tag set
  (each **file** contributes its DB tags; each **subdir** contributes its own
  computed set).

Pipeline under test: ``--store`` → ``--tag-add`` (per path) → ``--extract`` →
``--refresh-extracted-tags``.

Assertions: ``find <files>/_tags | sort`` matches the expected path set, and each
symlink’s textual target matches :func:`_expected_symlink_text`.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

SHADUP_PY = Path(__file__).resolve().parent.parent / "shadup.py"

ROOT_LINK_NAME = "__root__"


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
    file_map: dict[str, frozenset[str]] = {
        p.as_posix(): t for p, t in rel_pairs
    }

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


def _link_relpath_under_files(tag: str, dir_key: str) -> Path:
    """Path under ``files/`` for the symlink mirroring directory ``dir_key``."""
    base = Path("_tags") / tag
    if not dir_key:
        return base / ROOT_LINK_NAME
    return base.joinpath(*dir_key.split("/"))


def _expected_symlink_text(files_root: Path, tag: str, dir_key: str) -> str:
    """Text stored in the symlink (relative to its parent directory)."""
    link = files_root / _link_relpath_under_files(tag, dir_key)
    target_dir = files_root / dir_key if dir_key else files_root
    return os.path.relpath(target_dir, link.parent)


def expected__tags_find_lines(files_root: Path, tags_by_dir: dict[str, frozenset[str]]) -> str:
    """Sorted ``find`` lines (relative to ``files/``) for everything under ``_tags``."""
    paths: set[str] = set()
    tags_anchor = files_root / "_tags"

    def add_path_and_ancestors(p: Path) -> None:
        cur = p.resolve()
        anchor = tags_anchor.resolve()
        while True:
            rel = os.path.relpath(cur, files_root.resolve())
            if rel != ".":
                paths.add(rel.replace(os.sep, "/"))
            if cur == anchor or cur.resolve() == anchor:
                break
            if cur.parent == cur:
                break
            cur = cur.parent

    add_path_and_ancestors(files_root / "_tags")

    for dir_key, tags in tags_by_dir.items():
        for tag in tags:
            add_path_and_ancestors(files_root / _link_relpath_under_files(tag, dir_key))

    return "\n".join(sorted(paths)) + ("\n" if paths else "")


def expected_symlink_checks(
    files_root: Path, tags_by_dir: dict[str, frozenset[str]]
) -> list[tuple[Path, str]]:
    """(path relative to ``files_root``, expected readlink text)."""
    out: list[tuple[Path, str]] = []
    for dir_key, tags in tags_by_dir.items():
        for tag in sorted(tags):
            rel = _link_relpath_under_files(tag, dir_key)
            txt = _expected_symlink_text(files_root, tag, dir_key)
            out.append((rel, txt))
    return out


def _dir_key_from_link_rel(rel: Path) -> str:
    """Inverse of :func:`_link_relpath_under_files` (directory key, ``\"\"`` = root)."""
    parts = rel.parts
    assert parts[0] == "_tags"
    body = parts[2:]
    if not body or body == (ROOT_LINK_NAME,):
        return ""
    return str(Path(*body))


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
    """Store → tag-add → extract → refresh; compare ``find`` and symlink targets."""
    shadir, files_root, file_specs = three_level_fixture
    assert len(file_specs) == 14

    tags_by_dir = compute_dir_tags_from_file_specs(files_root, file_specs)
    want_find = expected__tags_find_lines(files_root, tags_by_dir)
    want_links = expected_symlink_checks(files_root, tags_by_dir)

    tmp_path = files_root.parent
    _run_shadup(tmp_path, shadir, ["--store", "files"])

    for orig, tags in file_specs:
        assert orig.is_symlink()
        _run_shadup(tmp_path, shadir, ["--tag-add", str(orig), *tags])

    _run_shadup(tmp_path, shadir, ["--extract", "files"])
    _run_shadup(tmp_path, shadir, ["--refresh-extracted-tags"])

    got_find = _find_sorted_relative_to_files(files_root)
    assert got_find == want_find, (
        "sorted find mismatch:\n--- expected ---\n"
        f"{want_find}\n--- actual ---\n{got_find}"
    )

    for rel, want_text in want_links:
        link = files_root / rel
        assert link.is_symlink(), f"expected symlink at {link}"
        assert os.readlink(link) == want_text, (
            f"{link}: got {os.readlink(link)!r} want {want_text!r}"
        )
    for rel, _want_text in want_links:
        link = files_root / rel
        target = (link.parent / os.readlink(link)).resolve()
        dir_key = _dir_key_from_link_rel(rel)
        expect = (files_root / dir_key).resolve() if dir_key else files_root.resolve()
        assert target == expect, f"{link} -> {target} expected {expect}"
