#!/usr/bin/env venv-run
"""onboardctl -- direct onboard debug CLI (bypasses DMZ / manage).

Usage:
  onboardctl <subcommand> <zonespec> [extraargs...]

Talks to boards on their local HTTP debug port (default :5000). See
thermo/onboard/AGENTS.md and onboardctl/README.md.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional, Sequence, Type

from command import COMMAND_CLASSES, Subcommand, build_parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args_list: List[str] = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    try:
        ns = parser.parse_args(args_list)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 1
    command_cls: Type[Subcommand] = ns.command_cls
    cmd = command_cls(ns)
    return cmd.run()


if __name__ == "__main__":
    raise SystemExit(main())
