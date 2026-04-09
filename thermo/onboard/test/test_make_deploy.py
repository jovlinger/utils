"""
Tests for `make deploy` (thermo/onboard/Makefile).

Drive commands via mock_cmd (Python) from the sister `bin` repo: symlink test/bin/git,
test/bin/docker, etc. to mock_cmd.py, prepend that test/bin to PATH, run `make deploy`
against a fixture repo tree — or prepend the sister bin repo so `mock_cmd.py` is on PATH.

Layout matches the rest of this tree: sibling repo at ``<parent-of-utils>/bin`` (same as
``Makefile`` ``RUN_WITH_BIN`` / ``stage-docker-import.sh``).

mock_cmd (sister ``bin/mock_cmd.py``) matches invocations by exact ``cmd + args`` string
(see ``MOCK_FILE`` JSON). Tests register expectations via ``set_mock`` (imported), not
``--mock_match``, because the CLI misparses ``docker compose up -d`` (``-d`` looks like an option).

Run: from thermo/onboard with venv active, or via test/run.sh.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Tuple


def _utils_root() -> Path:
    """``utils`` checkout root (parent of ``thermo/``)."""
    # thermo/onboard/test/<this file> -> test -> onboard -> thermo -> utils
    return Path(__file__).resolve().parent.parent.parent.parent


def sister_bin_dir() -> Path:
    """
    Directory of the sister ``bin`` repo (``bin/`` next to ``utils/``).

    Same convention as ``thermo/onboard/Makefile`` ``$(CURDIR)/../../../bin`` and
    ``stage-docker-import.sh`` ``$ONBOARD/../../../bin``.
    """
    return (_utils_root().parent / "bin").resolve()


def mock_cmd_path() -> Path:
    """Path to ``mock_cmd.py`` in the sister bin repo."""
    return sister_bin_dir() / "mock_cmd.py"


def onboard_dir() -> Path:
    """``thermo/onboard`` directory (contains ``Makefile``, ``install/``)."""
    return Path(__file__).resolve().parent.parent


@contextmanager
def sister_bin_first_on_path() -> Iterator[None]:
    """Prepend :func:`sister_bin_dir` to ``PATH``, then restore the previous value."""
    bin_dir = str(sister_bin_dir())
    old = os.environ.get("PATH")
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old or ''}"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old


def _mock_subprocess_env(mock_file: Path, home: Path, mock_bins: Path) -> Dict[str, str]:
    """Environment for ``make deploy`` so ``git``/``docker`` hit mock_cmd and config is isolated."""
    env = os.environ.copy()
    env["MOCK_FILE"] = str(mock_file)
    env["HOME"] = str(home)
    env.pop("CR_PAT", None)
    path = env.get("PATH", "")
    env["PATH"] = f"{mock_bins}{os.pathsep}{path}"
    return env


def _load_mock_cmd_module(mpy: Path, mock_file: Path) -> Any:
    """
    Load sister ``mock_cmd.py`` with ``MOCK_FILE`` set.

    We call ``reset_mocks`` / ``set_mock`` directly: the CLI ``--mock_match`` parser
    misparses args that include ``-d`` (e.g. ``docker compose up -d``).
    """
    os.environ["MOCK_FILE"] = str(mock_file)
    mod_name = f"_thermo_mock_cmd_{id(mock_file)}"
    spec = importlib.util.spec_from_file_location(mod_name, mpy)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load mock_cmd from {mpy}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _configure_mock_expectations(mpy: Path, mock_file: Path) -> None:
    """Program :func:`_load_mock_cmd_module` with :data:`_DEPLOY_EXPECTED_INVOCATIONS`."""
    mod = _load_mock_cmd_module(mpy, mock_file)
    mod.reset_mocks()
    for spec in _DEPLOY_EXPECTED_INVOCATIONS:
        cmd = spec[0]
        argv = list(spec[1:])
        mod.set_mock(cmd, argv, 0, "", "")


def _symlink_mock_bins(target_dir: Path, mpy: Path) -> None:
    """``git`` and ``docker`` -> ``mock_cmd.py`` (basename becomes command name)."""
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in ("git", "docker"):
        link = target_dir / name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(mpy)


# deploy.sh + deploy-compose.sh (default ``up``) invoke exactly these mocked commands.
_DEPLOY_EXPECTED_INVOCATIONS: Tuple[Tuple[str, ...], ...] = (
    ("git", "pull"),
    ("docker", "compose", "pull"),
    ("docker", "compose", "up", "-d"),
    ("docker", "compose", "ps"),
)


class TestSisterBinPathHelpers(unittest.TestCase):
    """Same layout as ``Makefile`` / ``stage-docker-import.sh`` (sibling ``bin`` next to ``utils``)."""

    def test_sister_bin_dir_is_parent_of_utils_named_bin(self) -> None:
        utils = _utils_root()
        expected = (utils.parent / "bin").resolve()
        self.assertEqual(sister_bin_dir(), expected)

    def test_sister_bin_first_on_path_restores_path(self) -> None:
        old = os.environ.get("PATH")
        with sister_bin_first_on_path():
            head = os.environ["PATH"].split(os.pathsep, 1)[0]
            self.assertEqual(head, str(sister_bin_dir()))
        self.assertEqual(os.environ.get("PATH"), old)


class TestMakeDeployMakefile(unittest.TestCase):
    """Exercise `make deploy` without touching real git remotes or Docker."""

    @unittest.skipUnless(
        mock_cmd_path().is_file(),
        f"sister bin repo missing mock_cmd.py (expected {mock_cmd_path()})",
    )
    def test_make_deploy_runs_install_deploy_with_repo_path(self) -> None:
        """
        Fixture: temp directory with ``.git`` and ``thermo/onboard/install/deploy-compose.sh``
        (``deploy.sh`` comes from this package via ``make``). ``git``/``docker`` are mock_cmd
        symlinks; expectations match :data:`_DEPLOY_EXPECTED_INVOCATIONS`.
        """
        mpy = mock_cmd_path()
        onboard = onboard_dir()
        src_compose = onboard / "install" / "deploy-compose.sh"
        self.assertTrue(src_compose.is_file(), msg=f"missing {src_compose}")

        with tempfile.TemporaryDirectory() as td_raw:
            td = Path(td_raw)
            fixture = td / "repo"
            fixture.mkdir()
            mock_file = td / "mock_config.json"
            mock_bins = td / "mockbins"
            home = td / "home"
            home.mkdir()

            install_rel = Path("thermo/onboard/install")
            inst = fixture / install_rel
            inst.mkdir(parents=True)
            shutil.copy2(src_compose, inst / "deploy-compose.sh")

            subprocess.run(["git", "init"], cwd=str(fixture), check=True, capture_output=True)
            self.assertTrue((fixture / ".git").exists())

            _symlink_mock_bins(mock_bins, mpy)
            env = _mock_subprocess_env(mock_file, home, mock_bins)
            _configure_mock_expectations(mpy, mock_file)

            result = subprocess.run(
                [
                    "make",
                    "-C",
                    str(onboard),
                    "deploy",
                    f"DEPLOY_REPO={fixture}",
                ],
                env=env,
                capture_output=True,
                text=True,
            )

            self.assertEqual(
                result.returncode,
                0,
                msg=f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}",
            )
            self.assertIn("Deploy complete.", result.stdout)
            self.assertIn(f"[deploy] REPO_PATH={fixture}", result.stdout)
            self.assertNotIn("ERROR: No mock configured", result.stderr)

            config = json.loads(mock_file.read_text())
            for spec in _DEPLOY_EXPECTED_INVOCATIONS:
                key = f"{spec[0]} {' '.join(spec[1:])}"
                self.assertIn(key, config)
                self.assertEqual(config[key]["exit_code"], 0)

    def test_deploy_repo_override_reaches_deploy_sh(self) -> None:
        """``make deploy DEPLOY_REPO=...`` passes ``REPO_PATH`` to ``install/deploy.sh``."""
        onboard = onboard_dir()
        fake_repo = "/tmp/thermo_make_deploy_dry_run_placeholder"
        out = subprocess.run(
            ["make", "-n", "-C", str(onboard), "deploy", f"DEPLOY_REPO={fake_repo}"],
            capture_output=True,
            text=True,
            check=True,
        )
        self.assertIn(f'REPO_PATH="{fake_repo}"', out.stdout)


if __name__ == "__main__":
    unittest.main()
