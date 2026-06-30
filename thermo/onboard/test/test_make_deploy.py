"""
Tests for `make deploy` (thermo/onboard/Makefile).

Drive commands via :func:`mock_cmd_path`: symlink fixture ``test/bin/git``,
``test/bin/docker``, etc. to that file, prepend that directory to ``PATH``, run
``make deploy`` against a fixture repo tree.

Layout: ``run-with-stdout-logged.py`` / ``mock_cmd.py`` are snapshotted under
``extdeps/`` at the utils repo root (refresh: ``make -C extdeps all`` from repo root).
``Makefile`` ``RUN_WITH_BIN`` / ``stage-docker-import.sh`` use
``../../extdeps/run-with-stdout-logged.py`` from ``thermo/onboard``.

mock_cmd matches invocations by exact ``cmd + args`` string (see ``MOCK_FILE`` JSON).
Tests register expectations via ``set_mock`` (imported), not ``--mock_match``, because
the CLI misparses ``docker compose up -d`` (``-d`` looks like an option).

Run: from thermo/onboard with venv active, or via test/run.sh.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterator, Optional, Tuple

import pytest


def _utils_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent.parent


def thermo_extdeps_dir() -> Path:
    return (_utils_root() / "extdeps").resolve()


def mock_cmd_path() -> Path:
    return thermo_extdeps_dir() / "mock_cmd.py"


def onboard_dir() -> Path:
    return Path(__file__).resolve().parent.parent


@contextmanager
def thermo_extdeps_first_on_path() -> Iterator[None]:
    bin_dir = str(thermo_extdeps_dir())
    old = os.environ.get("PATH")
    os.environ["PATH"] = f"{bin_dir}{os.pathsep}{old or ''}"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("PATH", None)
        else:
            os.environ["PATH"] = old


def _mock_subprocess_env(
    mock_file: Path, home: Path, mock_bins: Path
) -> Dict[str, str]:
    env = os.environ.copy()
    real_home = Path(env.get("HOME", os.path.expanduser("~")))
    real_cargo = real_home / ".cargo/bin/cargo"
    env["MOCK_FILE"] = str(mock_file)
    env["HOME"] = str(home)
    env.pop("CR_PAT", None)
    path = env.get("PATH", "")
    env["PATH"] = f"{mock_bins}{os.pathsep}{path}"
    if real_cargo.is_file():
        env["CARGO"] = str(real_cargo)
    if (real_home / ".cargo").is_dir():
        env["CARGO_HOME"] = str(real_home / ".cargo")
    if (real_home / ".rustup").is_dir():
        env["RUSTUP_HOME"] = str(real_home / ".rustup")
    return env


def _load_mock_cmd_module(mpy: Path, mock_file: Path) -> Any:
    os.environ["MOCK_FILE"] = str(mock_file)
    mod_name = f"_thermo_mock_cmd_{id(mock_file)}"
    spec = importlib.util.spec_from_file_location(mod_name, mpy)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load mock_cmd from {mpy}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _configure_mock_expectations(
    mpy: Path,
    mock_file: Path,
    repo: Optional[Path] = None,
) -> None:
    mod = _load_mock_cmd_module(mpy, mock_file)
    mod.reset_mocks()
    for spec in _DEPLOY_EXPECTED_INVOCATIONS:
        cmd = spec[0]
        argv = list(spec[1:])
        mod.set_mock(cmd, argv, 0, "", "")
    if repo is not None:
        mod.set_mock(
            "git", ["-C", str(repo), "rev-parse", "HEAD"], 0, "abcdef1234567890\n", ""
        )
        mod.set_mock(
            "git", ["-C", str(repo), "rev-parse", "--short", "HEAD"], 0, "abcdef1\n", ""
        )
        mod.set_mock(
            "git",
            ["-C", str(repo), "rev-parse", "--abbrev-ref", "HEAD"],
            0,
            "rooms\n",
            "",
        )
        mod.set_mock(
            "git",
            ["-C", str(repo), "status", "--porcelain", "--untracked-files=no"],
            0,
            "",
            "",
        )


def _symlink_mock_bins(target_dir: Path, mpy: Path) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in ("git", "docker", "ssh"):
        link = target_dir / name
        if link.exists() or link.is_symlink():
            link.unlink()
        link.symlink_to(mpy)


_DEPLOY_EXPECTED_INVOCATIONS: Tuple[Tuple[str, ...], ...] = (
    ("docker", "info"),
    ("git", "pull"),
    ("docker", "compose", "pull"),
    ("docker", "compose", "up", "-d"),
    ("docker", "compose", "ps"),
)


def _copy_pizero2w_backend(fixture: Path, onboard: Path) -> None:
    backend_rel = Path("thermo/onboard/hardware/pizero2w/install")
    backend_dst = fixture / backend_rel
    backend_src = onboard / "hardware" / "pizero2w" / "install"
    backend_dst.mkdir(parents=True)
    for name in ("deploy.sh", "deploy-compose.sh", "docker-compose.yml"):
        shutil.copy2(backend_src / name, backend_dst / name)


def _copy_kitchen_zone_env(fixture: Path, text: str) -> None:
    zone_dst = fixture / "thermo" / "onboard" / "zones" / "kitchen"
    zone_dst.mkdir(parents=True)
    (zone_dst / "zone.env").write_text(text, encoding="ascii")


def test_thermo_extdeps_dir() -> None:
    utils = _utils_root()
    expected = (utils / "extdeps").resolve()
    assert thermo_extdeps_dir() == expected


def test_thermo_extdeps_first_on_path_restores_path() -> None:
    old = os.environ.get("PATH")
    with thermo_extdeps_first_on_path():
        head = os.environ["PATH"].split(os.pathsep, 1)[0]
        assert head == str(thermo_extdeps_dir())
    assert os.environ.get("PATH") == old


@pytest.mark.skipif(
    not mock_cmd_path().is_file(),
    reason=f"extdeps missing mock_cmd.py (expected {mock_cmd_path()})",
)
def test_make_deploy_runs_install_deploy_with_repo_path() -> None:
    mpy = mock_cmd_path()
    onboard = onboard_dir()
    thermo_root = onboard.parent
    src_loader = thermo_root / "config" / "source-thermo-env.sh"
    assert src_loader.is_file(), f"missing {src_loader}"

    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        fixture = td / "repo"
        fixture.mkdir()
        mock_file = td / "mock_config.json"
        mock_bins = td / "mockbins"
        home = td / "home"
        home.mkdir()

        cfg = fixture / "thermo" / "config"
        cfg.mkdir(parents=True)
        shutil.copy2(src_loader, cfg / "source-thermo-env.sh")
        (cfg / "ci.env").write_text(
            "DMZ_SCHEME=http\n"
            "DMZ_HOST=127.0.0.1\n"
            "DMZ_PORT=5000\n"
            "ONBOARD_DEPLOY_BACKEND=pizero2w\n",
            encoding="ascii",
        )
        _copy_kitchen_zone_env(
            fixture,
            "DMZ_SCHEME=http\n"
            "DMZ_HOST=127.0.0.1\n"
            "DMZ_PORT=5000\n"
            "ZONE_NAME=kitchen\n"
            "ONBOARD_DEPLOY_BACKEND=pizero2w\n"
            "ONBOARD_HARDWARE_PROFILE=pi_zero_2w_htu21d_ir\n",
        )
        _copy_pizero2w_backend(fixture, onboard)

        subprocess.run(
            ["git", "init"], cwd=str(fixture), check=True, capture_output=True
        )
        assert (fixture / ".git").exists()

        _symlink_mock_bins(mock_bins, mpy)
        env = _mock_subprocess_env(mock_file, home, mock_bins)
        env["THERMO_ENV_FILE"] = "config/ci.env"
        # deploy.sh uses /run and /var/log by default; macOS has no writable /run - keep everything under td.
        deploy_fake_root = td / "deploy_fake_root"
        deploy_fake_root.mkdir()
        env["THERMO_DEPLOY_ROOT"] = str(deploy_fake_root)
        _configure_mock_expectations(mpy, mock_file, fixture)

        result = subprocess.run(
            [
                "make",
                "-C",
                str(onboard),
                "deploy-zone",
                "THERMO_ENV_FILE=onboard/zones/kitchen/zone.env",
                "EXPECTED_ONBOARD_DEPLOY_BACKEND=pizero2w",
                f"DEPLOY_REPO={fixture}",
            ],
            env=env,
            capture_output=True,
            text=True,
        )

        assert (
            result.returncode == 0
        ), f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert "Deploy complete." in result.stdout
        assert "Deploy backend=pizero2w" in result.stdout
        assert "pizero2w-deploy" in result.stdout
        assert f'REPO_PATH="{fixture}"' in result.stdout
        assert "ERROR: No mock configured" not in result.stderr
        metadata = (
            fixture
            / "thermo"
            / "onboard"
            / "hardware"
            / "pizero2w"
            / "install"
            / ".deploy-metadata.env"
        ).read_text(encoding="ascii")
        assert "THERMO_DEPLOY_GIT_SHA_SHORT=abcdef1\n" in metadata
        assert "THERMO_DEPLOY_GIT_BRANCH=rooms\n" in metadata
        assert "THERMO_DEPLOY_GIT_DIRTY=0\n" in metadata
        assert "THERMO_DEPLOY_ENV_FILE=onboard/zones/kitchen/zone.env\n" in metadata
        assert "THERMO_DEPLOY_BACKEND=pizero2w\n" in metadata
        assert "THERMO_DEPLOY_HARDWARE_PROFILE=pi_zero_2w_htu21d_ir\n" in metadata

        config = json.loads(mock_file.read_text())
        for spec in _DEPLOY_EXPECTED_INVOCATIONS:
            key = f"{spec[0]} {' '.join(spec[1:])}"
            assert key in config
            assert config[key]["exit_code"] == 0


@pytest.mark.skipif(
    not mock_cmd_path().is_file(),
    reason=f"extdeps missing mock_cmd.py (expected {mock_cmd_path()})",
)
def test_make_deploy_dispatches_to_remote_pizero2w_host() -> None:
    mpy = mock_cmd_path()
    onboard = onboard_dir()
    thermo_root = onboard.parent
    src_loader = thermo_root / "config" / "source-thermo-env.sh"
    assert src_loader.is_file(), f"missing {src_loader}"

    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        fixture = td / "repo"
        fixture.mkdir()
        mock_file = td / "mock_config.json"
        mock_bins = td / "mockbins"
        home = td / "home"
        home.mkdir()

        cfg = fixture / "thermo" / "config"
        cfg.mkdir(parents=True)
        shutil.copy2(src_loader, cfg / "source-thermo-env.sh")
        (cfg / "ci.env").write_text(
            "DMZ_SCHEME=http\n"
            "DMZ_HOST=127.0.0.1\n"
            "DMZ_PORT=5000\n"
            "ZONE_NAME=kitchen\n"
            "ONBOARD_DEPLOY_BACKEND=pizero2w\n"
            "ONBOARD_DEPLOY_HOST=pizerokitchen.local\n"
            "ONBOARD_DEPLOY_USER=johan\n"
            "ONBOARD_DEPLOY_REPO=/home/johan/github.com/jovlinger/utils\n"
            "ONBOARD_DEPLOY_ENV_FILE=config/ci.env\n",
            encoding="ascii",
        )
        _copy_kitchen_zone_env(
            fixture,
            "DMZ_SCHEME=http\n"
            "DMZ_HOST=127.0.0.1\n"
            "DMZ_PORT=5000\n"
            "ZONE_NAME=kitchen\n"
            "ONBOARD_DEPLOY_BACKEND=pizero2w\n"
            "ONBOARD_DEPLOY_HOST=pizerokitchen.local\n"
            "ONBOARD_DEPLOY_USER=johan\n"
            "ONBOARD_DEPLOY_REPO=/home/johan/github.com/jovlinger/utils\n"
            "ONBOARD_DEPLOY_ENV_FILE=onboard/zones/kitchen/zone.env\n",
        )
        _copy_pizero2w_backend(fixture, onboard)

        subprocess.run(
            ["git", "init"], cwd=str(fixture), check=True, capture_output=True
        )
        assert (fixture / ".git").exists()

        _symlink_mock_bins(mock_bins, mpy)
        env = _mock_subprocess_env(mock_file, home, mock_bins)
        env["THERMO_ENV_FILE"] = "config/ci.env"
        mod = _load_mock_cmd_module(mpy, mock_file)
        mod.reset_mocks()
        remote_cmd = (
            "cd /home/johan/github.com/jovlinger/utils && git fetch origin master && git checkout master "
            "&& git pull --ff-only origin master && ONBOARD_DEPLOY_LOCAL=1 ONBOARD_DEPLOY_SKIP_GIT_PULL=1 "
            'make -C thermo/onboard deploy-zone THERMO_ENV_FILE="onboard/zones/kitchen/zone.env" '
            'EXPECTED_ONBOARD_DEPLOY_BACKEND=pizero2w DEPLOY_REPO="$(pwd)"'
        )
        assert "git checkout master" in remote_cmd
        assert "deploy-zone" in remote_cmd
        assert "make -C thermo/onboard deploy ZONE=" not in remote_cmd
        mod.set_mock("ssh", ["johan@pizerokitchen.local", remote_cmd], 0, "", "")

        result = subprocess.run(
            [
                "make",
                "-C",
                str(onboard),
                "deploy-zone",
                "THERMO_ENV_FILE=onboard/zones/kitchen/zone.env",
                "EXPECTED_ONBOARD_DEPLOY_BACKEND=pizero2w",
                f"DEPLOY_REPO={fixture}",
            ],
            env=env,
            capture_output=True,
            text=True,
        )

        assert (
            result.returncode == 0
        ), f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        assert "Deploy backend=pizero2w" in result.stdout
        assert "Remote deploy to johan@pizerokitchen.local" in result.stdout
        assert "ERROR: No mock configured" not in result.stderr

        config = json.loads(mock_file.read_text())
        key = f"ssh johan@pizerokitchen.local {remote_cmd}"
        assert key in config
        assert config[key]["exit_code"] == 0


def test_deploy_repo_override_reaches_deploy_sh() -> None:
    onboard = onboard_dir()
    fake_repo = "/tmp/thermo_make_deploy_dry_run_placeholder"
    out = subprocess.run(
        [
            "make",
            "-n",
            "-C",
            str(onboard),
            "deploy-zone",
            "THERMO_ENV_FILE=onboard/zones/kitchen/zone.env",
            "EXPECTED_ONBOARD_DEPLOY_BACKEND=pizero2w",
            f"DEPLOY_REPO={fake_repo}",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    assert f'REPO_PATH="{fake_repo}"' in out.stdout


def test_zone_build_scopes_to_deploy_backend() -> None:
    onboard = onboard_dir()
    kitchen = onboard / "zones" / "kitchen"
    office = onboard / "zones" / "office"
    kitchen_out = subprocess.run(
        ["make", "-n", "-C", str(kitchen), "build"],
        capture_output=True,
        text=True,
        check=True,
    )
    office_out = subprocess.run(
        ["make", "-n", "-C", str(office), "build"],
        capture_output=True,
        text=True,
        check=True,
    )
    assert "ONBOARD_BUILD_BACKEND=pizero2w" in kitchen_out.stdout
    assert "hardware/pizero2w" in kitchen_out.stdout
    assert "hardware/pico2w" not in kitchen_out.stdout
    assert "ONBOARD_BUILD_BACKEND=pico2w" in office_out.stdout
    assert "hardware/pico2w" in office_out.stdout
    assert "hardware/pizero2w" not in office_out.stdout
