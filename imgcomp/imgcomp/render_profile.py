"""Optional per-phase render timing (perf_counter nanoseconds)."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter_ns
from typing import Iterator


@dataclass
class RenderProfile:
    """Accumulated phase timings for one render call."""

    phases_ns: dict[str, int] = field(default_factory=dict)

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        start = perf_counter_ns()
        try:
            yield
        finally:
            self.phases_ns[name] = self.phases_ns.get(name, 0) + (perf_counter_ns() - start)

    def ms(self, name: str) -> float:
        return self.phases_ns.get(name, 0) / 1_000_000.0

    def total_ms(self) -> float:
        return sum(self.phases_ns.values()) / 1_000_000.0

    def as_dict_ms(self) -> dict[str, float]:
        return {name: ns / 1_000_000.0 for name, ns in sorted(self.phases_ns.items())}


@contextmanager
def phase(profile: RenderProfile | None, name: str) -> Iterator[None]:
    if profile is None:
        yield
        return
    with profile.phase(name):
        yield
