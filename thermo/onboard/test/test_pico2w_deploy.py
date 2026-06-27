from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_pico2w_deploy_fails_before_build_when_boot_volume_hangs(
    tmp_path: Path,
) -> None:
    volume = tmp_path / "RP2350"
    volume.mkdir()
    env_file = tmp_path / "office.env"
    env_file.write_text(
        "\n".join(
            [
                "ONBOARD_DEPLOY_BACKEND=pico2w",
                "ZONE_NAME=office",
                "PICO2W_TARGET=thumbv8m.main-none-eabihf",
                f"PICO2W_UF2_VOLUME={volume}",
                f"PICO2W_UF2_PATH={tmp_path / 'firmware.uf2'}",
                "PICO2W_WIFI_PASSWORD=test-password",
                "PICO2W_ZONE_PRIVATE_KEY_B64=test-key",
                "",
            ]
        ),
        encoding="ascii",
    )
    mock_bin = tmp_path / "bin"
    mock_bin.mkdir()
    mock_ls = mock_bin / "ls"
    mock_ls.write_text("#!/bin/sh\nsleep 30\n", encoding="ascii")
    mock_ls.chmod(mock_ls.stat().st_mode | stat.S_IXUSR)
    mock_mount = mock_bin / "mount"
    mock_mount.write_text(
        f"#!/bin/sh\necho '/dev/disk9s1 on {volume} (msdos, local)'\n",
        encoding="ascii",
    )
    mock_mount.chmod(mock_mount.stat().st_mode | stat.S_IXUSR)

    env = os.environ.copy()
    env["PATH"] = f"{mock_bin}{os.pathsep}{env.get('PATH', '')}"
    env["REPO_PATH"] = str(repo_root())
    env["THERMO_ENV_FILE"] = str(env_file)
    env["PICO2W_VOLUME_READY_TIMEOUT_SECS"] = "1"

    result = subprocess.run(
        [
            "/bin/sh",
            str(repo_root() / "thermo/onboard/hardware/pico2w/install/deploy.sh"),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
    )

    combined_output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "Pico boot volume is mounted but not responding" in combined_output
    assert "cargo" not in combined_output.lower()
