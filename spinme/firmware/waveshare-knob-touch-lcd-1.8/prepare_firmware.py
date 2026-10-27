#!/usr/bin/env python3
"""Embed glyphs.bin and compile the host uimk2 sources into this firmware."""

from __future__ import annotations

from pathlib import Path


def _firmware_dir() -> Path:
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path.cwd()


def write_glyph_embed(firmware_dir: Path) -> None:
    """Link glyphs.bin into .rodata so the ESP32 flash cache maps it."""
    blob = firmware_dir / "glyphs.bin"
    if not blob.is_file():
        raise SystemExit("glyphs.bin missing")
    asm = firmware_dir / "src" / "glyphs_embed.S"
    asm.write_text(
        "\n".join(
            [
                "/* Generated. glyphs.bin is mapped through the flash cache. */",
                ".section .rodata",
                ".global glyphs_bin_start",
                ".global glyphs_bin_end",
                ".align 4",
                "glyphs_bin_start:",
                '.incbin "{0}"'.format(blob),
                "glyphs_bin_end:",
                "",
            ]
        )
    )


def add_uimk2(env, firmware_dir: Path) -> None:
    uimk2 = (firmware_dir / ".." / ".." / "uimk2").resolve()
    env.Append(CPPPATH=[str(uimk2)])
    env.BuildSources(
        env.subst("$BUILD_DIR/uimk2"),
        str(uimk2),
        src_filter="+<uimk2_event.c> +<uimk2_host.c> +<uimk2_zlist.c>",
    )


def main(env=None) -> None:
    firmware_dir = _firmware_dir()
    write_glyph_embed(firmware_dir)
    if env is not None:
        add_uimk2(env, firmware_dir)


try:
    Import("env")  # type: ignore[name-defined]  # noqa: F821
except NameError:
    if __name__ == "__main__":
        main()
else:
    main(env)  # type: ignore[name-defined]  # noqa: F821
