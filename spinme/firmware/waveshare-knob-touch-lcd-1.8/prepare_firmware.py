#!/usr/bin/env python3
"""Embed glyphs.bin, write the gitignored WiFi header, and compile uimk2."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Optional


def _firmware_dir() -> Path:
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path.cwd()


def _wifi_json_path(firmware_dir: Path) -> Optional[Path]:
    """Main-checkout spinme/wifi.local.json, or SPINME_WIFI_JSON when set."""
    env_path = os.environ.get("SPINME_WIFI_JSON", "").strip()
    if env_path:
        return Path(env_path)
    try:
        common = subprocess.check_output(
            ["git", "rev-parse", "--git-common-dir"],
            cwd=str(firmware_dir),
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return None
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = (firmware_dir / common_path).resolve()
    return common_path.parent / "spinme" / "wifi.local.json"


def _c_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped + '"'


def write_wifi_header(firmware_dir: Path) -> None:
    """Write include/wifi_local.h. Empty SSID when the json is absent.

    The header is gitignored. Passwords stay in wifi.local.json.
    """
    source = _wifi_json_path(firmware_dir)
    dest = firmware_dir / "include" / "wifi_local.h"
    ssid = ""
    password = ""
    if source is not None and source.is_file():
        with source.open(encoding="utf-8") as handle:
            data = json.load(handle)
        wifi = data.get("wifi", {})
        ssid = str(wifi.get("ssid", ""))
        password = str(wifi.get("pass", ""))
        print(
            "wifi header written from {0} (ssid set: {1})".format(
                source, bool(ssid.strip())
            )
        )
    else:
        shown = source if source is not None else "(no path)"
        print(
            "wifi json missing: {0}; writing empty SSID placeholders".format(shown)
        )
    dest.write_text(
        "\n".join(
            [
                "#pragma once",
                "/* Generated from wifi.local.json. Do not commit. */",
                "#define SPINME_WIFI_SSID {0}".format(_c_string(ssid)),
                "#define SPINME_WIFI_PASS {0}".format(_c_string(password)),
                "",
            ]
        )
    )


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
        src_filter="+<uimk2_event.c> +<uimk2_host.c> +<uimk2_zlist.c> "
        "+<uimk2_blit.c> +<uimk2_blit_pie.S>",
    )


def main(env=None) -> None:
    firmware_dir = _firmware_dir()
    write_wifi_header(firmware_dir)
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
