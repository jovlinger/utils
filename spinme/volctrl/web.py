"""Throwaway Flask harness: one page plus healthz, bound to a zone."""

from __future__ import annotations

from html import escape
from typing import Any

from flask import Flask

from .zone import FakeZone


def create_app(zone: FakeZone | None = None) -> Flask:
    active = zone if zone is not None else FakeZone()
    app = Flask(__name__)

    @app.get("/healthz")
    def healthz() -> str:
        return "ok\n"

    @app.get("/")
    def index() -> str:
        state: dict[str, Any] = active.get_state()
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
            "</body></html>"
        )

    return app


def main() -> None:
    create_app().run(host="127.0.0.1", port=5000)


if __name__ == "__main__":
    main()
