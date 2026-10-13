"""Throwaway Flask harness: follow view, transport, and volume for one zone."""

from __future__ import annotations

from html import escape
from typing import Any

from flask import Flask, Response, redirect, request

from .zone import FakeZone, Zone


def _follow_page(state: dict[str, Any]) -> str:
    artist = escape(str(state.get("artist") or ""))
    title = escape(str(state.get("title") or ""))
    status = escape(str(state.get("status") or ""))
    volume = escape(str(state.get("volume", "")))
    return (
        "<!DOCTYPE html><html><body>"
        f'<p id="artist">{artist}</p>'
        f'<p id="title">{title}</p>'
        f'<p id="status">{status}</p>'
        f'<p id="volume">{volume}</p>'
        '<form method="post" action="/play"><button>play</button></form>'
        '<form method="post" action="/pause"><button>pause</button></form>'
        '<form method="post" action="/toggle"><button>toggle</button></form>'
        '<form method="post" action="/volume">'
        '<button name="volume" value="minus">down</button>'
        '<button name="volume" value="plus">up</button>'
        "</form>"
        "</body></html>"
    )


def create_app(zone: Zone | None = None) -> Flask:
    active: Zone = zone if zone is not None else FakeZone()
    app = Flask(__name__)

    @app.get("/healthz")
    def healthz() -> str:
        return "ok\n"

    @app.get("/")
    def index() -> str:
        return _follow_page(active.get_state())

    def _back() -> Response:
        return redirect("/")

    @app.post("/play")
    def play() -> Response:
        active.play()
        return _back()

    @app.post("/pause")
    def pause() -> Response:
        active.pause()
        return _back()

    @app.post("/toggle")
    def toggle() -> Response:
        active.toggle()
        return _back()

    @app.post("/volume")
    def volume() -> Response:
        raw = request.form.get("volume", "")
        if raw == "plus":
            active.volume_up()
        elif raw == "minus":
            active.volume_down()
        else:
            active.set_volume(int(raw))
        return _back()

    return app


def main() -> None:
    create_app().run(host="127.0.0.1", port=5000)


if __name__ == "__main__":
    main()
