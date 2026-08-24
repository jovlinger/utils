"""Live Tk preview with optional downsampled display."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from typing import Callable, Optional

from imgcomp.compositor import Compositor
from imgcomp.object import Object
from imgcomp.surface import Surface


@dataclass(frozen=True)
class DisplayMapping:
    """Map between viewport pixels and on-screen preview pixels."""

    scale: float
    offset_x: float
    offset_y: float

    def viewport_from_display(self, display_x: float, display_y: float) -> tuple[float, float]:
        return (
            (display_x - self.offset_x) / self.scale,
            (display_y - self.offset_y) / self.scale,
        )


class LivePreview:
    """Show a compositor buffer in a Tk window."""

    def __init__(
        self,
        compositor: Compositor,
        root_object: Object,
        *,
        title: str = "imgcomp preview",
        max_display_side: int = 800,
        on_frame: Optional[Callable[[Surface], None]] = None,
    ) -> None:
        self._compositor = compositor
        self._root_object = root_object
        self._title = title
        self._max_display_side = max_display_side
        self._on_frame = on_frame
        self._surface: Optional[Surface] = None
        self._scale = 1.0
        self._offset_x = 0.0
        self._offset_y = 0.0
        self._photo: Optional[tk.PhotoImage] = None
        self._drag_last: Optional[tuple[float, float]] = None

        self._tk = tk.Tk()
        self._tk.title(title)
        self._label = tk.Label(self._tk)
        self._label.pack()
        self._label.bind("<Button-1>", self._on_touch)
        self._label.bind("<B1-Motion>", self._on_drag)
        self._label.bind("<MouseWheel>", self._on_scroll)
        self.refresh()

    @property
    def surface(self) -> Surface:
        if self._surface is None:
            raise RuntimeError("preview has no rendered surface yet")
        return self._surface

    def refresh(self) -> None:
        """Re-render the scene and update the preview image."""
        self._surface = self._compositor.render(self._root_object)
        if self._on_frame is not None:
            self._on_frame(self._surface)
        self._photo, self._scale, self._offset_x, self._offset_y = _surface_to_photo(
            self._surface,
            self._max_display_side,
        )
        self._label.configure(image=self._photo)
        self._label.image = self._photo  # type: ignore[attr-defined]

    def run(self) -> None:
        """Start the Tk main loop."""
        self._tk.mainloop()

    def _on_touch(self, event: tk.Event) -> None:
        vx, vy = self._viewport_from_display(float(event.x), float(event.y))
        self._compositor.dispatch_event(self._root_object, "touch", vx, vy)
        self._drag_last = (vx, vy)

    def _on_drag(self, event: tk.Event) -> None:
        vx, vy = self._viewport_from_display(float(event.x), float(event.y))
        if self._drag_last is None:
            self._drag_last = (vx, vy)
            return
        last_x, last_y = self._drag_last
        self._compositor.dispatch_event(
            self._root_object,
            "drag",
            vx,
            vy,
            dx=vx - last_x,
            dy=vy - last_y,
        )
        self._drag_last = (vx, vy)

    def _viewport_from_display(self, display_x: float, display_y: float) -> tuple[float, float]:
        return (
            (display_x - self._offset_x) / self._scale,
            (display_y - self._offset_y) / self._scale,
        )

    def _on_scroll(self, event: tk.Event) -> None:
        vx, vy = self._viewport_from_display(float(event.x), float(event.y))
        delta = float(getattr(event, "delta", 0.0))
        self._compositor.dispatch_event(
            self._root_object,
            "scroll",
            vx,
            vy,
            delta=delta,
        )


def _surface_to_photo(
    surface: Surface,
    max_display_side: int,
) -> tuple[tk.PhotoImage, float, float, float]:
    from PIL import Image, ImageTk

    image = Image.frombytes(
        "RGBA",
        (surface.width, surface.height),
        _surface_bytes(surface),
    )
    scale = min(1.0, max_display_side / max(image.width, image.height))
    display_w = max(1, int(round(image.width * scale)))
    display_h = max(1, int(round(image.height * scale)))
    if scale < 1.0:
        image = image.resize((display_w, display_h), Image.Resampling.NEAREST)
    safe_scale = scale if scale > 0.0 else 1.0
    return ImageTk.PhotoImage(image), safe_scale, 0.0, 0.0


def _surface_bytes(surface: Surface) -> bytes:
    if hasattr(surface, "to_bytes"):
        return surface.to_bytes()  # type: ignore[attr-defined]
    rows = bytearray()
    for _x, _y, color in surface.iter_pixels():
        rows.extend(color)
    return bytes(rows)
