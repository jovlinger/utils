"""Write square and round previews of the status screen."""

from __future__ import annotations

from pathlib import Path

from screenmock.layout import Status, render_legacy_round, render_round, render_square


def write_previews(directory: Path, status: Status | None = None) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    shown = status if status is not None else Status()
    paths = {
        "status-square.png": render_square(shown),
        "status-round.png": render_round(shown),
        "legacy-round.png": render_legacy_round(shown),
    }
    written: list[Path] = []
    for name, image in paths.items():
        path = directory / name
        image.save(path)
        written.append(path)
    return written


def main() -> None:
    preview = Path(__file__).resolve().parent / "preview"
    for path in write_previews(preview):
        print(path)


if __name__ == "__main__":
    main()
