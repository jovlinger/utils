"""Zone surface the Flask harness calls. Volume on screen is always get_state."""

from __future__ import annotations

from typing import Any, Protocol

from .api import VolumioAPI


class Zone(Protocol):
    def get_state(self) -> dict[str, Any]:
        """Player snapshot. Call again after every command; do not cache volume."""

    def play(self) -> None:
        ...

    def pause(self) -> None:
        ...

    def toggle(self) -> None:
        ...

    def set_volume(self, value: int) -> None:
        ...

    def volume_up(self) -> None:
        ...

    def volume_down(self) -> None:
        ...


class FakeZone:
    """In-memory player so the harness can run without the network."""

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

    def play(self) -> None:
        self.status = "play"

    def pause(self) -> None:
        self.status = "pause"

    def toggle(self) -> None:
        self.status = "pause" if self.status == "play" else "play"

    def set_volume(self, value: int) -> None:
        self.volume = max(0, min(100, value))

    def volume_up(self) -> None:
        self.set_volume(self.volume + 1)

    def volume_down(self) -> None:
        self.set_volume(self.volume - 1)


class VolumioZone:
    """One Volumio host. Commands go to the API; state is always re-read."""

    def __init__(self, api: VolumioAPI) -> None:
        self.api = api

    def get_state(self) -> dict[str, Any]:
        return self.api.get_state()

    def play(self) -> None:
        self.api.play()

    def pause(self) -> None:
        self.api.pause()

    def toggle(self) -> None:
        self.api.toggle()

    def set_volume(self, value: int) -> None:
        self.api.set_volume(value)

    def volume_up(self) -> None:
        self.api.volume_up()

    def volume_down(self) -> None:
        self.api.volume_down()
