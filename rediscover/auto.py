"""dd-trace-style auto-instrumentation via monkey-patching.

NOTE: Auto-instrumentation via monkey-patching is provided here as a
convenience. An alternative design worth considering: instead of implementing
our own collection layer, we could rely on dd-trace for tracing and implement
a bespoke Datadog Agent (dd-agent) that reads dd-trace spans and publishes
counter/timing data to Redis. This would give us richer trace context
(distributed trace IDs, service topology) at the cost of a dd-trace
dependency. For now we keep this self-contained.
"""

from __future__ import annotations

import inspect
import types
from typing import Any, Dict, Optional, Tuple

from rediscover.client import RedisDiscoverClient
from rediscover.decorators import profile

# Maps id(patched_object) -> {attr_name: original_callable}
_PATCHED: Dict[int, Dict[str, Any]] = {}


def _is_public_callable(name: str, obj: Any) -> bool:
    return (
        not name.startswith("_")
        and callable(obj)
        and not isinstance(obj, type)
    )


def patch_module(module: types.ModuleType, client: Optional[RedisDiscoverClient] = None) -> None:
    """Wrap all public callables in *module* with :func:`profile`."""
    obj_id = id(module)
    originals: Dict[str, Any] = {}

    for name in list(vars(module)):
        obj = getattr(module, name)
        if not _is_public_callable(name, obj):
            continue
        metric_name = f"{module.__name__}.{name}"
        wrapped = profile(name=metric_name, client=client)(obj)
        originals[name] = obj
        setattr(module, name, wrapped)

    if originals:
        _PATCHED[obj_id] = originals


def unpatch_module(module: types.ModuleType) -> None:
    """Restore original callables in *module*."""
    obj_id = id(module)
    originals = _PATCHED.pop(obj_id, {})
    for name, original in originals.items():
        setattr(module, name, original)


def patch_class(cls: type, client: Optional[RedisDiscoverClient] = None) -> None:
    """Wrap all public methods of *cls* with :func:`profile`."""
    obj_id = id(cls)
    originals: Dict[str, Any] = {}

    for name, obj in inspect.getmembers(cls, predicate=inspect.isfunction):
        if name.startswith("_"):
            continue
        metric_name = f"{cls.__module__}.{cls.__qualname__}.{name}"
        wrapped = profile(name=metric_name, client=client)(obj)
        originals[name] = obj
        setattr(cls, name, wrapped)

    if originals:
        _PATCHED[obj_id] = originals


def unpatch_class(cls: type) -> None:
    """Restore original methods on *cls*."""
    obj_id = id(cls)
    originals = _PATCHED.pop(obj_id, {})
    for name, original in originals.items():
        setattr(cls, name, original)
