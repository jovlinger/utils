"""Redis client with local batching and atomic INCRBY flushing."""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional

import redis


class RedisDiscoverClient:
    """Batches counter increments locally then flushes them atomically via INCRBY.

    Supports multiple Redis instances for redundancy; ``query()`` sums counts
    across all instances so each instance holds the same logical data over time.
    """

    KEY_PREFIX = "rediscover"

    def __init__(
        self,
        redis_urls: List[str],
        namespace: str = "default",
        flush_interval: float = 1.0,
        flush_threshold: int = 100,
    ) -> None:
        if not redis_urls:
            raise ValueError("At least one Redis URL must be provided.")
        self._namespace = namespace
        self._flush_interval = flush_interval
        self._flush_threshold = flush_threshold

        self._connections: List[redis.Redis] = [
            redis.Redis.from_url(url) for url in redis_urls
        ]

        self._local_batch: Dict[str, int] = {}
        self._lock = threading.Lock()

        self._stop_event = threading.Event()
        self._flush_thread = threading.Thread(
            target=self._flush_loop, daemon=True, name="rediscover-flush"
        )
        self._flush_thread.start()

    # ------------------------------------------------------------------
    # Key helpers
    # ------------------------------------------------------------------

    def _calls_key(self, name: str) -> str:
        return f"{self.KEY_PREFIX}:{self._namespace}:{name}:calls"

    def _time_key(self, name: str) -> str:
        return f"{self.KEY_PREFIX}:{self._namespace}:{name}:time_ms"

    def _pattern(self) -> str:
        return f"{self.KEY_PREFIX}:{self._namespace}:*"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def increment(self, name: str, count: int = 1, elapsed_ms: float = 0.0) -> None:
        """Thread-safe accumulation into the local batch."""
        calls_key = self._calls_key(name)
        time_key = self._time_key(name)
        with self._lock:
            self._local_batch[calls_key] = self._local_batch.get(calls_key, 0) + count
            rounded = round(elapsed_ms)
            if rounded:
                self._local_batch[time_key] = (
                    self._local_batch.get(time_key, 0) + rounded
                )
            should_flush = len(self._local_batch) >= self._flush_threshold

        if should_flush:
            self.flush()

    def flush(self) -> None:
        """Push local batch to all Redis instances using INCRBY pipelines."""
        with self._lock:
            if not self._local_batch:
                return
            batch = self._local_batch.copy()
            self._local_batch.clear()

        for conn in self._connections:
            try:
                pipe = conn.pipeline(transaction=False)
                for key, delta in batch.items():
                    pipe.incrby(key, delta)
                pipe.execute()
            except redis.RedisError:
                # Silently drop on error — metrics are best-effort.
                pass

    def query(self) -> Dict[str, Dict[str, int]]:
        """Return aggregated counters across all Redis instances.

        Returns:
            ``{name: {"calls": int, "time_ms": int}}``
        """
        totals: Dict[str, Dict[str, int]] = {}
        prefix = f"{self.KEY_PREFIX}:{self._namespace}:"

        for conn in self._connections:
            try:
                keys = conn.keys(self._pattern())
            except redis.RedisError:
                continue

            if not keys:
                continue

            try:
                values = conn.mget(keys)
            except redis.RedisError:
                continue

            for raw_key, raw_val in zip(keys, values):
                key_str = (
                    raw_key.decode() if isinstance(raw_key, bytes) else raw_key
                )
                val = int(raw_val) if raw_val is not None else 0

                # Strip prefix to get "{name}:{metric}"
                inner = key_str[len(prefix):]
                if inner.endswith(":calls"):
                    name = inner[: -len(":calls")]
                    metric = "calls"
                elif inner.endswith(":time_ms"):
                    name = inner[: -len(":time_ms")]
                    metric = "time_ms"
                else:
                    continue

                entry = totals.setdefault(name, {"calls": 0, "time_ms": 0})
                entry[metric] += val

        return totals

    def reset(self, name: Optional[str] = None) -> None:
        """Delete keys for *name* (or all keys) across every Redis instance."""
        for conn in self._connections:
            try:
                if name is not None:
                    keys_to_delete = [self._calls_key(name), self._time_key(name)]
                    conn.delete(*keys_to_delete)
                else:
                    keys = conn.keys(self._pattern())
                    if keys:
                        conn.delete(*keys)
            except redis.RedisError:
                pass

    def close(self) -> None:
        """Flush pending data and stop the background thread."""
        self._stop_event.set()
        self.flush()
        self._flush_thread.join(timeout=self._flush_interval * 2)

    # ------------------------------------------------------------------
    # Background flush loop
    # ------------------------------------------------------------------

    def _flush_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self._flush_interval)
            self.flush()
