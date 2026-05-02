"""Install sys.settrace line profiling with optional Redis batching."""

from __future__ import annotations

import atexit
import os
import signal
import sys
import threading
from typing import Callable, List, Optional

from rediscover.distributed import DistConfig, RedisLineSink


_active_sink: Optional[RedisLineSink] = None
_trace_fn: Optional[Callable] = None
_shutdown_registered = False
_shutdown_lock = threading.Lock()


def _normalize_root(project_root: str) -> str:
    return os.path.abspath(os.path.expanduser(project_root))


def make_line_tracer(project_root: str, sink: RedisLineSink) -> Callable:
    """Build a trace function that counts ``line`` events under *project_root*."""
    root = _normalize_root(project_root)

    def tracer(frame, event, arg):  # noqa: ARG001
        if event != "line":
            return tracer
        try:
            co = frame.f_code
            fname = co.co_filename
            if fname.endswith(".py"):
                abs_path = os.path.abspath(fname)
            else:
                abs_path = fname
            try:
                rel = os.path.relpath(abs_path, root)
            except ValueError:
                return tracer
            if rel.startswith(".." + os.sep) or rel == "..":
                return tracer
            line_key = f"{rel}:{frame.f_lineno}"
            sink.incr(line_key, 1)
        except Exception:
            pass
        return tracer

    return tracer


def _shutdown() -> None:
    global _active_sink, _trace_fn, _shutdown_registered
    with _shutdown_lock:
        sys.settrace(None)
        threading.settrace(None)
        if _active_sink is not None:
            try:
                _active_sink.stop()
            except Exception:
                pass
            _active_sink = None
        _trace_fn = None
        _shutdown_registered = False


def _ensure_shutdown_hooks(sink: RedisLineSink) -> None:
    global _shutdown_registered
    if _shutdown_registered:
        return
    atexit.register(_shutdown)

    def _handle_signal(signum, frame):  # noqa: ARG001
        _shutdown()
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    try:
        signal.signal(signal.SIGINT, _handle_signal)
        signal.signal(signal.SIGTERM, _handle_signal)
    except (ValueError, OSError):
        pass
    _shutdown_registered = True


def install_distributed_line_trace(
    project_root: str,
    *,
    redis_urls: List[str],
    app: str = "myapp",
    env: str = "dev",
    run_id: Optional[str] = None,
    flush_interval_s: float = 2.0,
    flush_threshold: int = 5000,
    start_sink: bool = True,
) -> RedisLineSink:
    """Enable line tracing for code under *project_root*; counts go to Redis."""
    global _active_sink, _trace_fn

    if _active_sink is not None:
        raise RuntimeError("Distributed line trace is already installed.")

    cfg = DistConfig(
        redis_urls=list(redis_urls),
        app=app,
        env=env,
        flush_interval_s=flush_interval_s,
        flush_threshold=flush_threshold,
        run_id=run_id,
    )
    sink = RedisLineSink(cfg)
    if start_sink:
        sink.start()

    tr = make_line_tracer(project_root, sink)
    _active_sink = sink
    _trace_fn = tr
    sys.settrace(tr)
    threading.settrace(tr)
    _ensure_shutdown_hooks(sink)
    return sink
