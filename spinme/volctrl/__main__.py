"""
CLI: discover endpoint, read state, set volume, play/pause.
  python -m volctrl discover
  python -m volctrl state [--host HOST]
  python -m volctrl volume N | up | down [--host HOST]
  python -m volctrl play | pause | toggle [--host HOST]
Host defaults to VOLUMIO_HOST env or volumio.local.
"""

from __future__ import annotations

import argparse
import os
import sys

from .api import VolumioAPI
from .discover import discover, resolve_volumio_local


def _host_port(host: str | None, port: int = 3000) -> tuple[str, int]:
    host = host or os.environ.get("VOLUMIO_HOST", "volumio.local")
    return host, port


def cmd_discover(_: argparse.Namespace) -> int:
    found = discover()
    for addr, port in found:
        print(f"  {addr}:{port}")
    if not found:
        print("No Volumio found.", file=sys.stderr)
        return 1
    print()
    print(f"export VOLUMIO_HOST={found[0][0]}")
    return 0


def cmd_state(args: argparse.Namespace) -> int:
    host, port = _host_port(args.host)
    api = VolumioAPI(host=host, port=port)
    try:
        s = api.get_state()
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    status = s.get("status") or "?"
    vol = s.get("volume", "?")
    title = (s.get("title") or "—").strip()
    artist = (s.get("artist") or "—").strip()
    print(f"status: {status}")
    print(f"volume: {vol}")
    print(f"track: {artist} — {title}")
    return 0


def cmd_volume(args: argparse.Namespace) -> int:
    host, port = _host_port(args.host)
    api = VolumioAPI(host=host, port=port)
    val = args.value.strip().lower()
    try:
        if val == "up":
            api.volume_up()
        elif val == "down":
            api.volume_down()
        else:
            api.set_volume(int(val))
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print("OK")
    return 0


def cmd_play_pause(args: argparse.Namespace) -> int:
    host, port = _host_port(args.host)
    api = VolumioAPI(host=host, port=port)
    try:
        if args.action == "play":
            api.play()
        elif args.action == "pause":
            api.pause()
        else:
            api.toggle()
    except OSError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    print("OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Volumio proof-of-concept controller")
    parser.add_argument("--host", default=os.environ.get("VOLUMIO_HOST"), help="Host (default: VOLUMIO_HOST or volumio.local)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("discover")

    state_p = sub.add_parser("state")
    state_p.set_defaults(handler=cmd_state)

    vol_p = sub.add_parser("volume")
    vol_p.add_argument("value", help="0-100, or up, or down")
    vol_p.set_defaults(handler=cmd_volume)

    sub.add_parser("play").set_defaults(handler=cmd_play_pause, action="play")
    sub.add_parser("pause").set_defaults(handler=cmd_play_pause, action="pause")
    sub.add_parser("toggle").set_defaults(handler=cmd_play_pause, action="toggle")

    args = parser.parse_args()
    if args.command == "discover":
        return cmd_discover(args)
    if args.command == "state":
        return cmd_state(args)
    if args.command == "volume":
        return cmd_volume(args)
    if args.command in ("play", "pause", "toggle"):
        return cmd_play_pause(args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
