"""Shared CLI helpers for onboardctl subcommands."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from transport import (
    AmbiguousTargetsError,
    FakeTransport,
    HttpTransport,
    Transport,
    require_single_target,
)
from zonespec import (
    BoardTarget,
    ZoneSpec,
    default_zones_dir,
    load_targets_from_zones_dir,
    parse_zonespec,
    resolve_zonespec,
)


def add_zonespec_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "zonespec",
        help=(
            "zone:NAME | hardware:TYPE | dialect:NAME | type:KIND | bare zone | "
            "ALL (every zone.env)"
        ),
    )


def resolve_targets_from_args(args: argparse.Namespace) -> List[BoardTarget]:
    spec = parse_zonespec(args.zonespec)
    zones_dir = Path(getattr(args, "zones_dir", "") or default_zones_dir())
    catalog = load_targets_from_zones_dir(zones_dir)
    return resolve_zonespec(spec, catalog)


def select_targets(
    args: argparse.Namespace,
    *,
    mutating: bool,
) -> List[BoardTarget]:
    targets = resolve_targets_from_args(args)
    if not targets:
        raise SystemExit(f"error: no boards match zonespec {args.zonespec!r}")
    if mutating and len(targets) > 1:
        names = ", ".join(t.zone_name for t in targets)
        raise SystemExit(
            f"error: zonespec {args.zonespec!r} matches multiple boards "
            f"({names}); narrow before mutating"
        )
    if mutating:
        require_single_target(targets, mutating=True, spec_text=args.zonespec)
    return targets


def transport_from_args(args: argparse.Namespace) -> Transport:
    fake = getattr(args, "fake_transport", None)
    if fake is not None:
        return fake  # type: ignore[return-value]
    return HttpTransport()
