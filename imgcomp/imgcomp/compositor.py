"""Compositor ABC."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from imgcomp.shape import Shape
from imgcomp.scene import Scene, as_z_list
from imgcomp.surface import Surface

EventKind = Literal["touch", "drag", "scroll"]


@dataclass(frozen=True)
class PickResult:
    """Topmost hit object and its local center-based coordinates."""

    target: Shape
    local_x: float
    local_y: float


class Compositor(ABC):
    """Render and hit-test a scene tree into a stated viewport size."""

    def __init__(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("width and height must be positive")
        self._width = width
        self._height = height

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    def viewport_to_root_local(self, vx: float, vy: float) -> tuple[float, float]:
        """Map viewport pixel coords to root-local center-based coords."""
        return (vx - self._width / 2.0, vy - self._height / 2.0)

    @abstractmethod
    def render(self, root: Scene) -> Surface:
        """Paint root into a new surface."""

    def render_png(self, root: Scene, path: Path | str) -> None:
        """Render root at full viewport resolution and write PNG."""
        self.render(root).write_png(path)

    @abstractmethod
    def pick(self, root: Scene, vx: float, vy: float) -> Optional[PickResult]:
        """Return the topmost hit in depth-first paint order, or None."""

    def dispatch_event(
        self,
        root: Scene,
        kind: EventKind,
        vx: float,
        vy: float,
        *,
        dx: float = 0.0,
        dy: float = 0.0,
        delta: float = 0.0,
    ) -> bool:
        """Route an event to the topmost hit object. Return True if handled."""
        picked = self.pick(root, vx, vy)
        if picked is None:
            return False
        target = picked.target
        local_x = picked.local_x
        local_y = picked.local_y
        if kind == "touch":
            target.on_touch(local_x, local_y)
        elif kind == "drag":
            target.on_drag(local_x, local_y, dx, dy)
        elif kind == "scroll":
            target.on_scroll(local_x, local_y, delta)
        else:
            raise ValueError(f"unknown event kind: {kind!r}")
        return True
