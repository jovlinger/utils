"""@count and @profile decorators plus module-level default client management."""

from __future__ import annotations

import functools
import time
from typing import Callable, List, Optional

from rediscover.client import RedisDiscoverClient

_default_client: Optional[RedisDiscoverClient] = None


# ---------------------------------------------------------------------------
# Module-level client management
# ---------------------------------------------------------------------------


def configure(
    redis_urls: List[str],
    namespace: str = "default",
    **kwargs,
) -> None:
    """Configure the module-level default client."""
    global _default_client
    _default_client = RedisDiscoverClient(redis_urls, namespace, **kwargs)


def get_default_client() -> RedisDiscoverClient:
    """Return the default client, raising if not yet configured."""
    if _default_client is None:
        raise RuntimeError(
            "No default rediscover client configured. "
            "Call rediscover.configure() first."
        )
    return _default_client


def flush() -> None:
    """Flush the default client."""
    get_default_client().flush()


def close() -> None:
    """Close the default client."""
    get_default_client().close()


# ---------------------------------------------------------------------------
# Decorators
# ---------------------------------------------------------------------------


def count(name: Optional[str] = None, client: Optional[RedisDiscoverClient] = None):
    """Decorator — counts each call to the wrapped function.

    Args:
        name: Metric name; defaults to ``module.qualname``.
        client: ``RedisDiscoverClient`` to use; falls back to the default client.
    """

    def decorator(func: Callable) -> Callable:
        metric_name = name or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _client = client if client is not None else get_default_client()
            try:
                return func(*args, **kwargs)
            finally:
                _client.increment(metric_name, count=1)

        return wrapper

    return decorator


def profile(name: Optional[str] = None, client: Optional[RedisDiscoverClient] = None):
    """Decorator — counts calls and records elapsed time in milliseconds.

    Args:
        name: Metric name; defaults to ``module.qualname``.
        client: ``RedisDiscoverClient`` to use; falls back to the default client.
    """

    def decorator(func: Callable) -> Callable:
        metric_name = name or f"{func.__module__}.{func.__qualname__}"

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            _client = client if client is not None else get_default_client()
            start = time.perf_counter()
            try:
                return func(*args, **kwargs)
            finally:
                elapsed_ms = (time.perf_counter() - start) * 1000.0
                _client.increment(metric_name, count=1, elapsed_ms=elapsed_ms)

        return wrapper

    return decorator
