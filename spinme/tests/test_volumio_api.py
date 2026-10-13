"""Volumio REST client against recorded HTTP fixtures, plus an optional live host."""

from __future__ import annotations

import json
import os
import urllib.request
from typing import Any

import pytest

from volctrl.api import VolumioAPI


class _Body:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._raw = json.dumps(payload).encode()

    def read(self) -> bytes:
        return self._raw

    def __enter__(self) -> _Body:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None


@pytest.fixture
def volumio_calls(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    seen: list[str] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float = 5) -> _Body:
        del timeout
        seen.append(req.full_url)
        if req.full_url.endswith("/getState"):
            return _Body(
                {
                    "status": "play",
                    "volume": 7,
                    "title": "Song",
                    "artist": "Ada",
                }
            )
        return _Body({"response": "ok"})

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    return seen


@pytest.fixture
def api(volumio_calls: list[str]) -> VolumioAPI:
    del volumio_calls
    return VolumioAPI(host="miniDSP-SHD.local", port=3000)


def test_get_state(api: VolumioAPI, volumio_calls: list[str]) -> None:
    state = api.get_state()
    assert state["status"] == "play"
    assert state["volume"] == 7
    assert state["title"] == "Song"
    assert state["artist"] == "Ada"
    assert volumio_calls == ["http://miniDSP-SHD.local:3000/api/v1/getState"]


def test_transport_and_volume(api: VolumioAPI, volumio_calls: list[str]) -> None:
    api.play()
    api.pause()
    api.toggle()
    api.set_volume(40)
    api.volume_up()
    api.volume_down()
    assert volumio_calls == [
        "http://miniDSP-SHD.local:3000/api/v1/commands/?cmd=play",
        "http://miniDSP-SHD.local:3000/api/v1/commands/?cmd=pause",
        "http://miniDSP-SHD.local:3000/api/v1/commands/?cmd=toggle",
        "http://miniDSP-SHD.local:3000/api/v1/commands/?cmd=volume&volume=40",
        "http://miniDSP-SHD.local:3000/api/v1/commands/?cmd=volume&volume=plus",
        "http://miniDSP-SHD.local:3000/api/v1/commands/?cmd=volume&volume=minus",
    ]


@pytest.mark.skipif(
    os.environ.get("VOLUMIO_LIVE") != "1",
    reason="set VOLUMIO_LIVE=1 to call the LAN host",
)
def test_live_get_state() -> None:
    host = os.environ.get("VOLUMIO_HOST", "miniDSP-SHD.local")
    state = VolumioAPI(host=host).get_state()
    assert "status" in state
    assert "volume" in state
