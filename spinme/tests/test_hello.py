"""Flask hello page is wired to FakeZone and exposes healthz."""

from __future__ import annotations

from volctrl.web import create_app
from volctrl.zone import FakeZone


def test_healthz() -> None:
    client = create_app(FakeZone()).test_client()
    response = client.get("/healthz")
    assert response.status_code == 200
    assert response.data == b"ok\n"


def test_index_shows_fake_zone() -> None:
    zone = FakeZone()
    zone.artist = "Ada"
    zone.title = "Ratchet"
    zone.status = "play"
    zone.volume = 41
    response = create_app(zone).test_client().get("/")
    assert response.status_code == 200
    body = response.data.decode()
    assert 'id="artist">Ada<' in body
    assert 'id="title">Ratchet<' in body
    assert 'id="status">play<' in body
    assert 'id="volume">41<' in body
