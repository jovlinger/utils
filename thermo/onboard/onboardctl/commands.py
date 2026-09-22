"""onboardctl subcommand implementations."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from cliutil import add_zonespec_argument, select_targets, transport_from_args
from command import Subcommand


class LogsCommand(Subcommand):
    command_names = ("logs",)
    doc_short = "Fetch onboard log ring (direct HTTP)"
    mutating = False

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        add_zonespec_argument(parser)

    def undo_hint(self) -> str:
        return "read-only / no undo"

    def run(self) -> int:
        targets = select_targets(self.args, mutating=False)
        transport = transport_from_args(self.args)
        for target in targets:
            data = transport.get_json(target, "/logs")
            print(f"# {target.zone_name} {target.base_url}/logs")
            print(json.dumps(data, indent=2, sort_keys=True))
        self.print_undo()
        return 0


class VersionCommand(Subcommand):
    command_names = ("version",)
    doc_short = "Show onboard version / identity from /healthz"
    mutating = False

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        add_zonespec_argument(parser)

    def undo_hint(self) -> str:
        return "read-only / no undo"

    def run(self) -> int:
        targets = select_targets(self.args, mutating=False)
        transport = transport_from_args(self.args)
        for target in targets:
            health = transport.get_json(target, "/healthz")
            out = {
                "zone": target.zone_name,
                "backend": target.backend,
                "base_url": target.base_url,
                "health": health,
            }
            print(json.dumps(out, indent=2, sort_keys=True))
        self.print_undo()
        return 0


class HealthzCommand(Subcommand):
    command_names = ("healthz",)
    doc_short = "Ping /healthz; report LAN connectivity per zone"
    doc_long = (
        "GET /healthz on each matched board and report ok/unreachable. "
        "Use zonespec ALL to probe every zone.env target. Exit 1 if any fail."
    )
    mutating = False

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        add_zonespec_argument(parser)
        parser.add_argument(
            "--timeout",
            type=float,
            default=3.0,
            help="HTTP timeout seconds per board (default 3)",
        )

    def undo_hint(self) -> str:
        return "read-only / no undo"

    def run(self) -> int:
        targets = select_targets(self.args, mutating=False)
        transport = transport_from_args(self.args)
        timeout = float(getattr(self.args, "timeout", 3.0))
        if hasattr(transport, "timeout_s"):
            transport.timeout_s = timeout  # type: ignore[attr-defined]
        rows: List[Dict[str, Any]] = []
        any_fail = False
        for target in targets:
            row: Dict[str, Any] = {
                "zone": target.zone_name,
                "backend": target.backend,
                "base_url": target.base_url,
                "ok": False,
            }
            try:
                health = transport.get_json(target, "/healthz")
                row["ok"] = True
                if isinstance(health, dict):
                    row["service"] = health.get("service")
                    row["hardware_backend"] = health.get("hardware_backend")
                    if "epoch_seconds" in health:
                        row["epoch_seconds"] = health.get("epoch_seconds")
                    elif "time" in health:
                        row["time"] = health.get("time")
                else:
                    row["health"] = health
            except RuntimeError as exc:
                any_fail = True
                row["error"] = str(exc)
            rows.append(row)
            status = "ok" if row["ok"] else "FAIL"
            detail = row.get("error") or row.get("service") or ""
            print(
                f"{status:4s}  {target.zone_name:12s}  {target.base_url}  {detail}",
                file=sys.stderr,
            )
        print(json.dumps({"zones": rows, "ok": not any_fail}, indent=2, sort_keys=True))
        self.print_undo()
        return 1 if any_fail else 0


class DeviceInfoCommand(Subcommand):
    command_names = ("deviceinfo",)
    doc_short = "Richer board identity (zone.env + /healthz)"
    mutating = False

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        add_zonespec_argument(parser)

    def undo_hint(self) -> str:
        return "read-only / no undo"

    def run(self) -> int:
        targets = select_targets(self.args, mutating=False)
        transport = transport_from_args(self.args)
        for target in targets:
            health: Any = {}
            try:
                health = transport.get_json(target, "/healthz")
            except RuntimeError as exc:
                health = {"error": str(exc)}
            out = {
                "zone": target.zone_name,
                "backend": target.backend,
                "hardware_profile": target.hardware_profile,
                "ir_protocol": target.ir_protocol,
                "send_behavior": target.send_behavior,
                "base_url": target.base_url,
                "env_path": str(target.env_path),
                "health": health,
            }
            print(json.dumps(out, indent=2, sort_keys=True))
        self.print_undo()
        return 0


def _parse_temp_c(raw: str) -> float:
    text = raw.strip().lower().rstrip("c")
    return float(text)


class SendCommandCommand(Subcommand):
    command_names = ("sendcommand",)
    doc_short = "Send HVAC-ish command to onboard (defaults applied)"
    mutating = True

    DEFAULTS = {
        "mode": "cool",
        "fan": "auto",
        "state": "on",
        "temp_c": 22.0,
    }

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        add_zonespec_argument(parser)
        parser.add_argument("--mode", default=cls.DEFAULTS["mode"])
        parser.add_argument("--fan", default=cls.DEFAULTS["fan"])
        parser.add_argument("--state", default=cls.DEFAULTS["state"])
        parser.add_argument(
            "--temp",
            default="22c",
            help="setpoint with optional c suffix (default 22c)",
        )

    def undo_hint(self) -> str:
        return (
            "onboardctl sendcommand <same-zonespec> --state=off "
            "(or restore prior mode/temp if known)"
        )

    def build_payload(self) -> Dict[str, Any]:
        power = str(self.args.state).lower() in ("on", "true", "1")
        return {
            "power": power,
            "mode": str(self.args.mode).upper(),
            "fan": str(self.args.fan).upper()
            if str(self.args.fan).lower() != "auto"
            else "AUTO",
            "temp_c": _parse_temp_c(str(self.args.temp)),
        }

    def run(self) -> int:
        targets = select_targets(self.args, mutating=True)
        transport = transport_from_args(self.args)
        payload = self.build_payload()
        target = targets[0]
        # Prefer /ui/command (pizero); fall back path documented for esp32 later.
        result = transport.post_json(target, "/ui/command", payload)
        print(json.dumps({"target": target.zone_name, "sent": payload, "result": result}, indent=2))
        self.print_undo()
        return 0


def _parse_bool(raw: str) -> bool:
    val = raw.strip().lower()
    if val in ("1", "true", "yes", "on"):
        return True
    if val in ("0", "false", "no", "off"):
        return False
    raise argparse.ArgumentTypeError(f"expected bool, got {raw!r}")


class SetVarCommand(Subcommand):
    command_names = ("setvar",)
    doc_short = "Set onboard debug knobs (--debug / --verbose)"
    mutating = True

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        add_zonespec_argument(parser)
        parser.add_argument("--debug", type=_parse_bool, default=None)
        parser.add_argument(
            "--verbose",
            type=int,
            choices=(0, 1, 2, 3, 4),
            default=None,
        )

    def undo_hint(self) -> str:
        parts: List[str] = []
        if self.args.debug is not None:
            parts.append(f"--debug={str(not self.args.debug).lower()}")
        if self.args.verbose is not None:
            parts.append("--verbose=0")
        if not parts:
            return "no changes requested"
        return "onboardctl setvar <same-zonespec> " + " ".join(parts)

    def run(self) -> int:
        if self.args.debug is None and self.args.verbose is None:
            print("error: pass --debug and/or --verbose", file=sys.stderr)
            return 2
        targets = select_targets(self.args, mutating=True)
        transport = transport_from_args(self.args)
        body: Dict[str, Any] = {}
        if self.args.debug is not None:
            body["debug"] = self.args.debug
        if self.args.verbose is not None:
            body["verbose"] = self.args.verbose
        target = targets[0]
        result = transport.post_json(target, "/debug/setvar", body)
        print(json.dumps({"target": target.zone_name, "set": body, "result": result}, indent=2))
        self.print_undo()
        return 0
