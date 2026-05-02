"""Redis-backed aggregation for distributed line-hit counts."""

from __future__ import annotations

import os
import socket
import threading
import time
from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional

import redis


def default_worker_id() -> str:
    return f"{socket.gethostname()}-{os.getpid()}"


@dataclass
class DistConfig:
    """Configuration for where and how line hits are stored in Redis."""

    redis_urls: List[str]
    app: str = "myapp"
    env: str = "dev"
    flush_interval_s: float = 2.0
    flush_threshold: int = 5000
    key_prefix: str = "disttrace"
    worker_id: str = ""
    run_id: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.redis_urls:
            raise ValueError("At least one Redis URL is required.")
        if not self.worker_id:
            object.__setattr__(self, "worker_id", default_worker_id())

    def root_key(self) -> str:
        return f"{self.key_prefix}:{self.app}:{self.env}"

    def line_hits_hash(self) -> str:
        return f"{self.root_key()}:line_hits"

    def run_line_hits_hash(self) -> Optional[str]:
        if not self.run_id:
            return None
        return f"{self.root_key()}:run:{self.run_id}:line_hits"

    def worker_heartbeat_key(self) -> str:
        return f"{self.root_key()}:workers:{self.worker_id}"


class RedisLineSink:
    """Batches per-line increments and flushes with HINCRBY pipelines."""

    def __init__(self, cfg: DistConfig) -> None:
        self._cfg = cfg
        self._connections: List[redis.Redis] = [
            redis.Redis.from_url(url) for url in cfg.redis_urls
        ]
        self._counts: Counter[str] = Counter()
        self._pending: int = 0
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def incr(self, line_key: str, n: int = 1) -> None:
        with self._lock:
            self._counts[line_key] += n
            self._pending += n
            should_flush = self._pending >= self._cfg.flush_threshold
        if should_flush:
            self.flush()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="rediscover-line-flush"
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=max(2.0, self._cfg.flush_interval_s * 2))
            self._thread = None
        self.flush()

    def flush(self) -> None:
        with self._lock:
            if not self._counts:
                return
            snap: Dict[str, int] = dict(self._counts)
            self._counts.clear()
            self._pending = 0

        main_hash = self._cfg.line_hits_hash()
        run_hash = self._cfg.run_line_hits_hash()
        heartbeat = self._cfg.worker_heartbeat_key()
        ttl = max(2, int(self._cfg.flush_interval_s * 2))
        ts = int(time.time())

        for conn in self._connections:
            try:
                pipe = conn.pipeline(transaction=False)
                for k, v in snap.items():
                    pipe.hincrby(main_hash, k, v)
                    if run_hash:
                        pipe.hincrby(run_hash, k, v)
                pipe.set(heartbeat, ts, ex=ttl)
                pipe.execute()
            except redis.RedisError:
                pass

    def _loop(self) -> None:
        while not self._stop.wait(self._cfg.flush_interval_s):
            self.flush()


def merge_line_hits_from_redis(
    redis_urls: List[str],
    app: str,
    env: str,
    key_prefix: str = "disttrace",
) -> Dict[str, int]:
    """Read line_hits hash from the primary Redis URL (first in the list).

    When multiple URLs are configured as mirrors, each holds the same logical
    counts; reading one avoids double-counting.
    """
    if not redis_urls:
        return {}
    root = f"{key_prefix}:{app}:{env}"
    key = f"{root}:line_hits"
    merged: Dict[str, int] = {}
    conn = redis.Redis.from_url(redis_urls[0])
    try:
        raw = conn.hgetall(key)
    except redis.RedisError:
        return {}
    for field, val in raw.items():
        fk = field.decode() if isinstance(field, bytes) else field
        try:
            iv = int(val)
        except (TypeError, ValueError):
            continue
        merged[fk] = merged.get(fk, 0) + iv
    return merged


def delete_line_hits(
    redis_urls: List[str], app: str, env: str, key_prefix: str = "disttrace"
) -> None:
    """Delete the main line_hits hash on every configured Redis instance."""
    root = f"{key_prefix}:{app}:{env}"
    key = f"{root}:line_hits"
    for url in redis_urls:
        conn = redis.Redis.from_url(url)
        try:
            conn.delete(key)
        except redis.RedisError:
            pass


def scan_workers(
    redis_urls: List[str], app: str, env: str, key_prefix: str = "disttrace"
) -> Dict[str, int]:
    """Return worker_id -> last heartbeat timestamp (best effort, first URL only)."""
    if not redis_urls:
        return {}
    root = f"{key_prefix}:{app}:{env}"
    pattern = f"{root}:workers:*"
    conn = redis.Redis.from_url(redis_urls[0])
    out: Dict[str, int] = {}
    prefix_workers = f"{root}:workers:"
    try:
        for k in conn.scan_iter(match=pattern, count=100):
            ks = k.decode() if isinstance(k, bytes) else k
            if not ks.startswith(prefix_workers):
                continue
            wid = ks[len(prefix_workers) :]
            try:
                raw = conn.get(k)
                if raw is None:
                    continue
                out[wid] = int(raw)
            except (redis.RedisError, TypeError, ValueError):
                continue
    except redis.RedisError:
        pass
    return out
