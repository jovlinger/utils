"""Rolling log buffer shared by HTTP debug endpoints and serial print."""

from __future__ import annotations

from typing import List, Optional


class LogRing:
    """Newest-first ring of stamped log lines (monotonic ms from boot)."""

    def __init__(
        self,
        capacity: int,
        boot_ms: int = 0,
        clock_ms: Optional[object] = None,
    ) -> None:
        self._capacity: int = capacity
        self._boot_ms: int = boot_ms
        self._lines: List[str] = []
        # clock_ms: zero-arg callable returning ms since some epoch; None -> 0.
        self._clock_ms = clock_ms

    def _now_ms(self) -> int:
        if self._clock_ms is None:
            return 0
        return int(self._clock_ms())  # type: ignore[operator]

    def add(self, line: str) -> str:
        stamp: int = self._now_ms() - self._boot_ms
        entry: str = "%dms %s" % (stamp, line)
        self._lines.append(entry)
        print(entry)
        while len(self._lines) > self._capacity:
            self._lines.pop(0)
        return entry

    def newest_first(self) -> List[str]:
        return list(reversed(self._lines))

    def __len__(self) -> int:
        return len(self._lines)
