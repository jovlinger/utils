"""Scene object ABC."""

from __future__ import annotations

from abc import ABC, abstractmethod

from imgcomp.rgba import RGBA


class Object(ABC):
    """Maps center-based local pixel coordinates to color and hit tests."""

    @abstractmethod
    def sample(self, x: float, y: float) -> RGBA:
        """Return straight RGBA at local coordinate (x, y)."""

    @abstractmethod
    def hit(self, x: float, y: float) -> bool:
        """Return True when local coordinate is inside the hit region."""

    def on_touch(self, x: float, y: float) -> None:
        """Handle a touch/click at local coordinates."""

    def on_drag(self, x: float, y: float, dx: float, dy: float) -> None:
        """Handle a drag at local coordinates."""

    def on_scroll(self, x: float, y: float, delta: float) -> None:
        """Handle a scroll wheel tick at local coordinates."""
