#!/usr/bin/env python3
"""Write a gitignored WiFi header and point GFX QSPI pixels at RAMWR 0x2C."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path


def _wifi_json_path(firmware_dir: Path) -> Path:
    env_path = os.environ.get("SPINME_WIFI_JSON", "").strip()
    if env_path:
        return Path(env_path)
    common = subprocess.check_output(
        ["git", "rev-parse", "--git-common-dir"],
        cwd=str(firmware_dir),
        text=True,
    ).strip()
    common_path = Path(common)
    if not common_path.is_absolute():
        common_path = (firmware_dir / common_path).resolve()
    return common_path.parent / "spinme" / "wifi.local.json"


def _c_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped + '"'


def write_wifi_header(firmware_dir: Path) -> None:
    source = _wifi_json_path(firmware_dir)
    dest = firmware_dir / "include" / "wifi_local.h"
    if not source.is_file():
        raise SystemExit("wifi json missing: {0}".format(source))
    with source.open() as handle:
        data = json.load(handle)
    wifi = data.get("wifi", {})
    ssid = str(wifi.get("ssid", ""))
    password = str(wifi.get("pass", ""))
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
    print("wifi header written (ssid set: {0})".format(bool(ssid.strip())))


def patch_qspi_ramwr(firmware_dir: Path) -> None:
    cpp = (
        firmware_dir
        / ".pio"
        / "libdeps"
        / "waveshare_knob_18_s3"
        / "GFX Library for Arduino"
        / "src"
        / "databus"
        / "Arduino_ESP32QSPI.cpp"
    )
    if not cpp.is_file():
        print("qspi bus not installed yet; skip pixel opcode patch")
        return
    text = cpp.read_text()
    text2 = text.replace("0x003C00", "0x002C00")
    one_bit = "SPI_TRANS_MULTILINE_CMD | SPI_TRANS_MULTILINE_ADDR"
    quad_cmd = (
        "SPI_TRANS_MODE_QIO | SPI_TRANS_MULTILINE_CMD | SPI_TRANS_MULTILINE_ADDR"
    )
    text2 = text2.replace(quad_cmd, one_bit)
    text2 = text2.replace(one_bit, quad_cmd)
    pixel_cmd = (
        "_spi_tran_ext.base.flags = SPI_TRANS_MODE_QIO;\n"
        "      _spi_tran_ext.base.cmd = 0x32;"
    )
    pixel_quad = (
        "_spi_tran_ext.base.flags = SPI_TRANS_MODE_QIO | "
        "SPI_TRANS_MULTILINE_CMD | SPI_TRANS_MULTILINE_ADDR;\n"
        "      _spi_tran_ext.base.cmd = 0x32;"
    )
    text2 = text2.replace(pixel_cmd, pixel_quad)
    text2 = text2.replace(
        "SPI_TRANS_USE_TXDATA | SPI_TRANS_MODE_QIO | SPI_TRANS_MULTILINE_CMD | SPI_TRANS_MULTILINE_ADDR",
        "SPI_TRANS_USE_TXDATA | SPI_TRANS_MODE_QIO",
    )
    text2 = text2.replace(
        "SPI_TRANS_USE_TXDATA | SPI_TRANS_MODE_QIO",
        "SPI_TRANS_USE_TXDATA | SPI_TRANS_MODE_QIO | SPI_TRANS_MULTILINE_CMD | SPI_TRANS_MULTILINE_ADDR",
    )
    if text2 == text:
        print("qspi quad command path already set")
        return
    cpp.write_text(text2)
    print("qspi commands and pixel headers set to 4-bit mode")


def _firmware_dir() -> Path:
    try:
        return Path(__file__).resolve().parent
    except NameError:
        return Path.cwd()


def main() -> None:
    firmware_dir = _firmware_dir()
    write_wifi_header(firmware_dir)
    patch_qspi_ramwr(firmware_dir)


try:
    Import  # type: ignore[name-defined]  # noqa: F821
except NameError:
    if __name__ == "__main__":
        main()
else:
    # PlatformIO loads this file as a pre-script with Import() already defined.
    main()
