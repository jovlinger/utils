"""ABC subcommand registry for onboardctl."""

from __future__ import annotations

import argparse
import sys
from abc import ABC, abstractmethod
from typing import ClassVar, List, Sequence, Type


class Subcommand(ABC):
    """One onboardctl subcommand: parser fragment, action, undo hint."""

    command_names: ClassVar[Sequence[str]] = ()
    doc_short: ClassVar[str] = ""
    doc_long: ClassVar[str] = ""
    mutating: ClassVar[bool] = False

    def __init__(self, args: argparse.Namespace) -> None:
        self.args = args

    @classmethod
    def register(cls, subparsers: argparse._SubParsersAction) -> None:
        for name in cls.command_names:
            parser = subparsers.add_parser(
                name,
                help=cls.doc_short,
                description=cls.doc_long or cls.doc_short,
            )
            cls.configure_parser(parser)
            parser.set_defaults(command_cls=cls)

    @classmethod
    @abstractmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        """Add subcommand-specific argparse arguments."""

    @abstractmethod
    def run(self) -> int:
        """Execute the subcommand; return process exit code."""

    def undo_hint(self) -> str:
        """How to undo, or an explicit read-only note."""
        return "read-only / no undo"

    def print_undo(self) -> None:
        print(f"undo: {self.undo_hint()}", file=sys.stderr)


class HelpCommand(Subcommand):
    command_names = ("help",)
    doc_short = "List registered subcommands"
    doc_long = "Print onboardctl subcommands and short help."

    @classmethod
    def configure_parser(cls, parser: argparse.ArgumentParser) -> None:
        return

    def run(self) -> int:
        names: List[str] = []
        for command_cls in COMMAND_CLASSES:
            for name in command_cls.command_names:
                names.append(f"  {name:16s} {command_cls.doc_short}")
        print("onboardctl subcommands:")
        if not names:
            print("  (none registered yet -- add Subcommand subclasses to COMMAND_CLASSES)")
        else:
            print("\n".join(names))
        print("\nUsage: onboardctl <subcommand> <zonespec> [extraargs...]")
        print("zonespec: zone:NAME | hardware:TYPE | dialect:NAME | type:KIND | bare zone name")
        self.print_undo()
        return 0


def _command_classes() -> List[Type[Subcommand]]:
    # Local import avoids circular import at module load.
    from commands import (
        DeviceInfoCommand,
        LogsCommand,
        SendCommandCommand,
        SetVarCommand,
        VersionCommand,
    )

    return [
        HelpCommand,
        LogsCommand,
        VersionCommand,
        DeviceInfoCommand,
        SendCommandCommand,
        SetVarCommand,
    ]


COMMAND_CLASSES: List[Type[Subcommand]] = []


def build_parser() -> argparse.ArgumentParser:
    global COMMAND_CLASSES
    if not COMMAND_CLASSES:
        COMMAND_CLASSES = _command_classes()
    parser = argparse.ArgumentParser(
        prog="onboardctl",
        description=(
            "Direct onboard debug CLI (bypasses DMZ). "
            "Sibling role to thermo/dmz/manage."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for command_cls in COMMAND_CLASSES:
        command_cls.register(sub)
    return parser
