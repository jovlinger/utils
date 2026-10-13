"""Follow view transport and volume, including a Volumio host binding."""

from __future__ import annotations

import json
import urllib.request
from typing import Any

import pytest

from volctrl.api import VolumioAPI
from volctrl.web import create_app
from volctrl.zone import FakeZone, VolumioZone


def test_transport_and_volume_follow_fake_zone() -> None:
    zone = FakeZone()
    client = create_app(zone).test_client()

    played = client.post("/play", follow_redirects=True)
    assert played.status_code == 200
    assert 'id="status">play<' in played.data.decode()

    paused = client.post("/pause", follow_redirects=True)
    assert 'id="status">pause<' in paused.data.decode()

    client.post("/toggle", follow_redirects=True)
    assert zone.status == "play"

    louder = client.post("/volume", data={"volume": "plus"}, follow_redirects=True)
    assert 'id="volume">21<' in louder.data.decode()
    quieter = client.post("/volume", data={"volume": "minus"}, follow_redirects=True)
    assert 'id="volume">20<' in quieter.data.decode()
    set_level = client.post("/volume", data={"volume": "55"}, follow_redirects=True)
    assert 'id="volume">55<' in set_level.data.decode()


def test_follow_view_bound_to_volumio_host(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float = 5) -> Any:
        del timeout
        seen.append(req.full_url)

        class _Body:
            def read(self) -> bytes:
                if req.full_url.endswith("/getState"):
                    payload = {
                        "status": "play",
                        "volume": 9,
                        "title": "Live",
                        "artist": "SHD",
                    }
                else:
                    payload = {"response": "ok"}
                return json.dumps(payload).encode()

            def __enter__(self) -> _Body:
                return self

            def __exit__(self, *_exc: object) -> None:
                return None

        return _Body()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    zone = VolumioZone(VolumioAPI(host="miniDSP-SHD.local", port=3000))
    response = create_app(zone).test_client().post("/play", follow_redirects=True)
    body = response.data.decode()
    assert 'id="artist">SHD<' in body
    assert 'id="title">Live<' in body
    assert 'id="status">play<' in body
    assert 'id="volume">9<' in body
    assert seen[0] == "http://miniDSP-SHD.local:3000/api/v1/commands/?cmd=play"
    assert seen[1] == "http://miniDSP-SHD.local:3000/api/v1/getState"
