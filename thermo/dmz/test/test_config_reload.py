"""Config reload from dmz-app.env and SIGUSR1 wiring."""

from __future__ import annotations

import os
import signal
import time
from pathlib import Path

import pytest

import app as app_module


def test_load_dmz_app_env_file(tmp_path: Path) -> None:
    env_file = tmp_path / "dmz-app.env"
    env_file.write_text(
        "LOG_LEVEL=WARNING\nOBSOLETE_LOG_SUPPRESS_REPEAT=5\n",
        encoding="utf-8",
    )
    assert app_module.load_dmz_app_env_file(env_file) is True
    assert os.environ["LOG_LEVEL"] == "WARNING"
    assert os.environ["OBSOLETE_LOG_SUPPRESS_REPEAT"] == "5"


def test_reload_dmz_config_from_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / "dmz-app.env"
    env_file.write_text(
        "LOG_LEVEL=ERROR\nOBSOLETE_LOG_SUPPRESS_REPEAT=1\n", encoding="utf-8"
    )
    monkeypatch.setenv("DMZ_APP_ENV_PATH", str(env_file))
    assert app_module.reload_dmz_config_from_disk() is True
    assert app_module.CONFIG["log_level"] == "ERROR"
    assert app_module.CONFIG["obsolete_log_suppress_repeat"] == 1
    assert app_module._obsolete_repeat_suppression_active() is False


def test_config_reload_wakes_long_poll_waiters() -> None:
    app_module.commands.clear()
    app_module.sensors.clear()
    app_module.commands["z1"] = [{"mode": "HEAT"}]
    app_module.sensors["z1"] = []
    with app_module._zone_command_clock_lock:
        app_module._last_zone_command_reply_at["z1"] = time.time()
        app_module._ui_command_received_at["z1"] = 0.0
    app_module._wake_long_poll_waiters_for_config_reload()
    with app_module._zone_command_clock_lock:
        sent = app_module._last_zone_command_reply_at["z1"]
        ui_last = app_module._ui_command_received_at["z1"]
    assert ui_last > sent


def test_install_config_reload_signal_registers_sigusr1() -> None:
    if not hasattr(signal, "SIGUSR1"):
        pytest.skip("SIGUSR1 not available")
    app_module._config_reload_signal_installed = False
    app_module.install_config_reload_signal()
    assert signal.getsignal(signal.SIGUSR1) is app_module._on_sigusr1_reload_config
