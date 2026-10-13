"""Now-playing comes from the hardwired Volumio host, including volume."""

from __future__ import annotations

from typing import Any

from volctrl.web import create_app
from volctrl.zone import HARDWIRED_VOLUMIO_HOST, hardwired_volumio_zone


class PlayerReportedZone:
    """Accepts volume commands but keeps reporting the player's own level."""

    def __init__(self) -> None:
        self.player_volume = 15
        self.commands: list[str] = []

    def get_state(self) -> dict[str, Any]:
        return {
            "status": "play",
            "artist": "SHD",
            "title": "Now",
            "volume": self.player_volume,
        }

    def play(self) -> None:
        self.commands.append("play")

    def pause(self) -> None:
        self.commands.append("pause")

    def toggle(self) -> None:
        self.commands.append("toggle")

    def set_volume(self, value: int) -> None:
        self.commands.append(f"set:{value}")

    def volume_up(self) -> None:
        self.commands.append("plus")

    def volume_down(self) -> None:
        self.commands.append("minus")


def test_hardwired_host() -> None:
    zone = hardwired_volumio_zone()
    assert zone.api.host == HARDWIRED_VOLUMIO_HOST
    assert HARDWIRED_VOLUMIO_HOST == "miniDSP-SHD.local"


def test_displayed_volume_is_player_value_not_the_request() -> None:
    zone = PlayerReportedZone()
    client = create_app(zone).test_client()
    response = client.post("/volume", data={"volume": "90"}, follow_redirects=True)
    body = response.data.decode()
    assert zone.commands == ["set:90"]
    assert 'id="volume">15<' in body
    assert 'id="status">play<' in body
    assert 'id="artist">SHD<' in body
    assert 'id="title">Now<' in body
