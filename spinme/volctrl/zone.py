"""In-memory zone used by the Flask harness before a real player is wired."""

from __future__ import annotations

from typing import Any


class FakeZone:
    """Fixed player snapshot the hello page can render without the network."""

    def __init__(self) -> None:
        self.status: str = "pause"
        self.volume: int = 20
        self.title: str = "Hello"
        self.artist: str = "FakeZone"

    def get_state(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "volume": self.volume,
            "title": self.title,
            "artist": self.artist,
        }
