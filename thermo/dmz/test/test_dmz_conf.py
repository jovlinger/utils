"""Tests for dmz.conf parsing and generated install artifacts."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

DMZ_DIR = Path(__file__).resolve().parent.parent
PARSE = DMZ_DIR / "install" / "parse-dmz-conf.sh"
DMZ_CONF = DMZ_DIR / "dmz.conf"


@pytest.mark.skipif(not PARSE.is_file(), reason="parse-dmz-conf.sh not in tree")
def test_repo_dmz_conf_parses(tmp_path: Path) -> None:
    out = tmp_path / "out"
    subprocess.run(
        ["/bin/sh", str(PARSE), str(DMZ_CONF), str(out)], check=True, timeout=10
    )
    net = (out / "network.conf").read_text(encoding="utf-8").strip()
    assert net.count(" ") == 1
    assert "/" in net.split()[0]
    env = (out / "dmz-app.env").read_text(encoding="utf-8")
    assert "PORT=" in env
    assert "OBSOLETE_LOG_SUPPRESS_REPEAT=10" in env
    assert "SUPPRESS_REPEAT_OBSOLETE_LOGS" not in env
    assert (out / "dns.conf").read_text(encoding="utf-8").strip()
    assert (out / "sshd-on-boot").read_text(encoding="utf-8").strip() in {"yes", "no"}


@pytest.mark.skipif(not PARSE.is_file(), reason="parse-dmz-conf.sh not in tree")
def test_parse_rejects_unknown_key(tmp_path: Path) -> None:
    conf = tmp_path / "bad.conf"
    conf.write_text(
        "NETWORK_ADDR=10.0.0.2/24\nNETWORK_GATEWAY=10.0.0.1\nFOO=bar\n",
        encoding="utf-8",
    )
    res = subprocess.run(
        ["/bin/sh", str(PARSE), str(conf), str(tmp_path / "out")],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert res.returncode != 0
    assert "unknown key" in res.stderr


@pytest.mark.skipif(not PARSE.is_file(), reason="parse-dmz-conf.sh not in tree")
def test_parse_generates_expected_network_line(tmp_path: Path) -> None:
    conf = tmp_path / "custom.conf"
    conf.write_text(
        "NETWORK_ADDR=10.1.1.2/24\n"
        "NETWORK_GATEWAY=10.1.1.1\n"
        "DNS_SERVERS=9.9.9.9,1.1.1.1\n"
        "SSHD_ON_BOOT=yes\n"
        "PORT=5001\n"
        "UI_PORT=8091\n"
        "THERMO_UI_PUBLIC_ORIGIN=http://ui.example:8091\n"
        "DMZ_PUBLIC_BASE_URL=https://dmz.example:5001\n"
        "LOG_LEVEL=WARNING\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    subprocess.run(["/bin/sh", str(PARSE), str(conf), str(out)], check=True, timeout=10)
    assert (out / "network.conf").read_text(
        encoding="utf-8"
    ) == "10.1.1.2/24 10.1.1.1\n"
    assert (out / "sshd-on-boot").read_text(encoding="utf-8").strip() == "yes"
    assert (out / "dns.conf").read_text(encoding="utf-8") == "9.9.9.9\n1.1.1.1\n"
    env = (out / "dmz-app.env").read_text(encoding="utf-8")
    assert "LOG_LEVEL=WARNING" in env
    assert "PORT=5001" in env
    assert "THERMO_UI_PUBLIC_ORIGIN=http://ui.example:8091" in env


@pytest.mark.skipif(not PARSE.is_file(), reason="parse-dmz-conf.sh not in tree")
def test_parse_rejects_bad_url(tmp_path: Path) -> None:
    conf = tmp_path / "bad-url.conf"
    conf.write_text(
        "NETWORK_ADDR=10.0.0.2/24\nNETWORK_GATEWAY=10.0.0.1\nDMZ_PUBLIC_BASE_URL=not-a-url\n",
        encoding="utf-8",
    )
    res = subprocess.run(
        ["/bin/sh", str(PARSE), str(conf), str(tmp_path / "out")],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )
    assert res.returncode != 0
    assert "DMZ_PUBLIC_BASE_URL" in res.stderr


@pytest.mark.skipif(not PARSE.is_file(), reason="parse-dmz-conf.sh not in tree")
def test_parse_propagates_obsolete_log_suppress_repeat(tmp_path: Path) -> None:
    conf = tmp_path / "custom.conf"
    conf.write_text(
        "NETWORK_ADDR=10.1.1.2/24\n"
        "NETWORK_GATEWAY=10.1.1.1\n"
        "OBSOLETE_LOG_SUPPRESS_REPEAT=5\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    subprocess.run(["/bin/sh", str(PARSE), str(conf), str(out)], check=True, timeout=10)
    env = (out / "dmz-app.env").read_text(encoding="utf-8")
    assert "OBSOLETE_LOG_SUPPRESS_REPEAT=5" in env


def test_app_obsolete_log_suppress_repeat_from_environ(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import app as dmz_module

    monkeypatch.setenv("OBSOLETE_LOG_SUPPRESS_REPEAT", "1")
    dmz_module.reload_dmz_config_from_environ()
    assert dmz_module.CONFIG["obsolete_log_suppress_repeat"] == 1
    assert dmz_module._obsolete_repeat_suppression_active() is False


def test_app_log_level_from_environ(monkeypatch: pytest.MonkeyPatch) -> None:
    import app as dmz_module

    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    dmz_module.reload_dmz_config_from_environ()
    assert dmz_module.CONFIG["log_level"] == "ERROR"
    assert dmz_module.logging.getLogger().level == dmz_module.logging.ERROR
