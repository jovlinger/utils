"""Write a round-glass PNG of the status UI.

Volumio status, artist, title, and volume are placeholders.
"""

from __future__ import annotations

from pathlib import Path

from screenmock.layout import Status, render_round, volumio_placeholder


def screenshot_path() -> Path:
    return Path(__file__).resolve().parent / "preview" / "screenshot.png"


def write_screenshot(path: Path | None = None, status: Status | None = None) -> Path:
    dest = path if path is not None else screenshot_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    shown = status if status is not None else volumio_placeholder()
    render_round(shown).save(dest)
    return dest


def main() -> None:
    print(write_screenshot())


if __name__ == "__main__":
    main()
