"""Run a script or module under distributed line tracing (``sys.settrace``)."""

from __future__ import annotations

import argparse
import os
import sys
from typing import List, Optional, Sequence, Tuple

from rediscover.line_tracer import install_distributed_line_trace


def _split_argv(argv: Optional[Sequence[str]] = None) -> Tuple[List[str], List[str]]:
    """Split ``argv`` at ``--`` into our flags and the target's ``sys.argv`` tail."""
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        i = argv.index("--")
        return argv[:i], argv[i + 1 :]
    except ValueError:
        return argv, []


def main(argv: Optional[Sequence[str]] = None) -> None:
    head, tail = _split_argv(argv)

    p = argparse.ArgumentParser(
        description="Run Python under line-level tracing; counts flush to Redis."
    )
    p.add_argument(
        "--root",
        required=True,
        help="Absolute or relative project root; only lines under this tree are counted.",
    )
    p.add_argument(
        "--redis",
        action="append",
        default=[],
        dest="redis_urls",
        metavar="URL",
        help="Redis URL (repeat for multiple instances). Default: redis://localhost:6379",
    )
    p.add_argument("--app", default=os.environ.get("REDISCOVER_LINE_APP", "myapp"))
    p.add_argument("--env", default=os.environ.get("REDISCOVER_LINE_ENV", "dev"))
    p.add_argument("--run-id", dest="run_id", default=None)
    p.add_argument("--flush-interval", type=float, default=2.0)
    p.add_argument("--flush-threshold", type=int, default=5000)
    p.add_argument("-m", "--module", dest="module", default=None)
    p.add_argument(
        "script",
        nargs="?",
        default=None,
        help="Path to a .py file to execute (if -m is not used).",
    )
    args = p.parse_args(head)

    redis_urls = args.redis_urls or ["redis://localhost:6379"]

    if not args.module and not args.script:
        p.error("Provide -m MODULE or a SCRIPT path (see --help).")

    install_distributed_line_trace(
        args.root,
        redis_urls=redis_urls,
        app=args.app,
        env=args.env,
        run_id=args.run_id,
        flush_interval_s=args.flush_interval,
        flush_threshold=args.flush_threshold,
    )

    import runpy

    if args.module:
        sys.argv = [args.module] + tail
        runpy.run_module(args.module, run_name="__main__", alter_sys=True)
    else:
        script = args.script
        sys.argv = [script] + tail
        runpy.run_path(script, run_name="__main__")


if __name__ == "__main__":
    main()
