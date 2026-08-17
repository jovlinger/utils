"""Tests for onboardctl transport gate and subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

ONBOARDCTL_DIR = Path(__file__).resolve().parents[1] / "onboardctl"
sys.path.insert(0, str(ONBOARDCTL_DIR))

from commands import (  # noqa: E402
    HealthzCommand,
    LogsCommand,
    SendCommandCommand,
    SetVarCommand,
)
from transport import AmbiguousTargetsError, FakeTransport, require_single_target  # noqa: E402
from zonespec import BoardTarget, load_targets_from_zones_dir, parse_zonespec, resolve_zonespec  # noqa: E402

ZONES = Path(__file__).resolve().parents[1] / "zones"


def _ns(**kwargs: object) -> argparse.Namespace:
    base = {"zones_dir": str(ZONES), "fake_transport": FakeTransport()}
    base.update(kwargs)
    return argparse.Namespace(**base)


def test_require_single_refuses_multi_when_mutating() -> None:
    targets = load_targets_from_zones_dir(ZONES)
    # Force multi by picking all
    with pytest.raises(AmbiguousTargetsError):
        require_single_target(targets, mutating=True, spec_text="hardware:pico")


def test_logs_prints_fake_payload(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeTransport(get_responses={"/logs": {"lines": ["a", "b"]}})
    args = _ns(zonespec="office", fake_transport=fake)
    rc = LogsCommand(args).run()
    assert rc == 0
    out = capsys.readouterr().out
    assert "office" in out
    assert '"a"' in out


def test_healthz_all_reports_connectivity(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeTransport(
        get_responses={
            "office:/healthz": {"ok": True, "service": "onboard-app"},
            "kitchen:/healthz": {"ok": True, "service": "onboard-app"},
        },
        get_errors={"bedroom:/healthz": RuntimeError("GET /healthz failed: timed out")},
    )
    args = _ns(zonespec="ALL", fake_transport=fake, timeout=1.0)
    rc = HealthzCommand(args).run()
    assert rc == 1
    captured = capsys.readouterr()
    assert "FAIL" in captured.err
    assert "bedroom" in captured.err
    summary = json.loads(captured.out)
    assert summary["ok"] is False
    by_zone = {row["zone"]: row for row in summary["zones"]}
    assert by_zone["office"]["ok"] is True
    assert by_zone["bedroom"]["ok"] is False


def test_healthz_all_ok_when_all_reachable(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeTransport(default_get={"ok": True, "service": "onboard-app"})
    args = _ns(zonespec="ALL", fake_transport=fake, timeout=1.0)
    rc = HealthzCommand(args).run()
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["ok"] is True
    assert len(summary["zones"]) == len(load_targets_from_zones_dir(ZONES))


def test_sendcommand_defaults_and_undo(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeTransport()
    args = _ns(
        zonespec="kitchen",
        fake_transport=fake,
        mode="cool",
        fan="auto",
        state="on",
        temp="22c",
    )
    cmd = SendCommandCommand(args)
    rc = cmd.run()
    assert rc == 0
    assert fake.post_log
    body = fake.post_log[0]["body"]
    assert body["power"] is True
    assert body["mode"] == "COOL"
    assert body["temp_c"] == 22.0
    err = capsys.readouterr().err
    assert "undo:" in err
    assert "--state=off" in err


def test_setvar_rejects_missing_flags() -> None:
    args = _ns(zonespec="office", debug=None, verbose=None)
    assert SetVarCommand(args).run() == 2


def test_setvar_records_post(capsys: pytest.CaptureFixture[str]) -> None:
    fake = FakeTransport()
    args = _ns(zonespec="office", fake_transport=fake, debug=True, verbose=2)
    rc = SetVarCommand(args).run()
    assert rc == 0
    assert fake.post_log[0]["body"] == {"debug": True, "verbose": 2}
    assert "--debug=false" in capsys.readouterr().err
