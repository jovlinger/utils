from __future__ import annotations

from pathlib import Path

import pytest

from common.deploy_metadata import deployment_post_metadata


def test_metadata_includes_hardware_and_git_from_env() -> None:
    meta = deployment_post_metadata(
        {
            "THERMO_DEPLOY_GIT_SHA": "abcdef1234567890",
            "THERMO_DEPLOY_GIT_SHA_SHORT": "abcdef1",
            "THERMO_DEPLOY_HARDWARE_PROFILE": "pi_zero_2w_htu21d_ir",
            "ZONE_NAME": "kitchen",
        }
    )
    assert meta["hardware_profile"] == "pi_zero_2w_htu21d_ir"
    assert meta["git_sha"] == "abcdef1234567890"
    assert meta["git_sha_short"] == "abcdef1"
    assert meta["zone_name"] == "kitchen"


def test_metadata_falls_back_to_onboard_hardware_profile() -> None:
    meta = deployment_post_metadata(
        {
            "ONBOARD_HARDWARE_PROFILE": "pico2w_aht20_ir",
            "ZONE_NAME": "office",
        }
    )
    assert meta["hardware_profile"] == "pico2w_aht20_ir"
    assert meta["zone_name"] == "office"


def test_metadata_resolves_git_from_repo(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    repo = tmp_path / "utils"
    repo.mkdir()
    (repo / ".git").mkdir()

    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        assert cmd[:3] == ["git", "-C", str(repo)]
        if cmd[3:] == ["rev-parse", "--is-inside-work-tree"]:
            return type("R", (), {"returncode": 0, "stdout": "true\n"})()
        if cmd[3:] == ["rev-parse", "HEAD"]:
            return type("R", (), {"returncode": 0, "stdout": "deadbeef\n"})()
        if cmd[3:] == ["rev-parse", "--short", "HEAD"]:
            return type("R", (), {"returncode": 0, "stdout": "deadbee\n"})()
        raise AssertionError(cmd)

    monkeypatch.setattr("common.deploy_metadata.subprocess.run", fake_run)
    meta = deployment_post_metadata(
        {
            "THERMO_DEPLOY_ROOT": str(repo),
            "ONBOARD_HARDWARE_PROFILE": "pico2w_aht20_ir",
        }
    )
    assert meta["git_sha"] == "deadbeef"
    assert meta["git_sha_short"] == "deadbee"
    assert meta["hardware_profile"] == "pico2w_aht20_ir"


def test_metadata_omits_git_when_repo_root_unknown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(cmd, **kwargs):  # type: ignore[no-untyped-def]
        return type("R", (), {"returncode": 128, "stdout": ""})()

    monkeypatch.setattr("common.deploy_metadata.subprocess.run", fake_run)
    meta = deployment_post_metadata(
        {
            "ONBOARD_HARDWARE_PROFILE": "pi_zero_2w_htu21d_ir",
            "ZONE_NAME": "kitchen",
        }
    )
    assert meta["hardware_profile"] == "pi_zero_2w_htu21d_ir"
    assert meta["zone_name"] == "kitchen"
    assert "git_sha" not in meta
    assert "git_sha_short" not in meta
