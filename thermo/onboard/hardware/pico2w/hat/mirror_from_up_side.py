#!/usr/bin/env python3
"""Build pico-side.vox by mirroring up-side.vox across X=0."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

GLYPH_MIRROR: Dict[str, str] = {
    "┌": "┐",
    "┐": "┌",
    "└": "┘",
    "┘": "└",
    "├": "┤",
    "┤": "├",
    "┬": "┬",
    "┴": "┴",
    "┼": "┼",
    "─": "─",
    "│": "│",
}

ROWS: Sequence[Tuple[str, str, str, str]] = (
    ("GP15", "P20", "GP16", "P21"),
    ("GP14", "P19", "GP17", "P22"),
    ("GND", "P18", "GND", "P23"),
    ("GP13", "P17", "GP18", "P24"),
    ("GP12", "P16", "GP19", "P25"),
    ("GP11", "P15", "GP20", "P26"),
    ("GP10", "P14", "GP21", "P27"),
    ("GND", "P13", "GND", "P28"),
    ("GP9", "P12", "GP22", "P29"),
    ("GP8", "P11", "RUN", "P30"),
    ("GP7", "P10", "GP26", "P31"),
    ("GP6", "P9", "GP27", "P32"),
    ("GND", "P8", "GND", "P33"),
    ("GP5", "P7", "GP28", "P34"),
    ("GP4", "P6", "GP35", "P35"),
    ("GP3", "P5", "3V3", "P36"),
    ("GP2", "P4", "3EN", "P37"),
    ("GND", "P3", "GND", "P38"),
    ("GP1", "P2", "VSYS", "P39"),
    ("GP0", "P1", "VBUS", "P40"),
)

ROW_MAP: Dict[str, str] = {up: pico for up, pico, _, _ in ROWS}
GND_ROWS: List[str] = [pico for up, pico, _, _ in ROWS if up == "GND"]

ROW_COMMENTS: Dict[str, str] = {
    "GP13": "IR RX: OUT GND VCC",
    "GP10": "IR TX: DAT GND VCC",
    "GP5": "SCL",
    "GP4": "AHT20 c3=SDA c4=SCL c5=GND c6=3V3; I2C0 GP4/SDA pin6 GP5/SCL pin7",
    "GP3": "3V3 tap",
}

COL_ASSERT_RE = re.compile(r"c(\d+)=(-\*|\*-|\||\+|-|[┌┐└┘├┤┬┴┼─│])")

GLYPH_MIRROR_COL_ASSERT: Dict[str, str] = {
    **GLYPH_MIRROR,
    "*-": "-*",
    "-*": "*-",
}


def mirror_col_comment(comment: str) -> str:
    def repl(match: re.Match[str]) -> str:
        col = 9 - int(match.group(1))
        token = GLYPH_MIRROR_COL_ASSERT.get(match.group(2), match.group(2))
        return f"c{col}={token}"

    return COL_ASSERT_RE.sub(repl, comment)


TRACE_CUSTOM: Dict[int, str] = {
    1: ".*.pico.*.",
    2: ".*.side.*.",
    20: ".*.usb..*.",
}


def mirror_chars(body: str) -> str:
    out = ["?"] * len(body)
    for index, char in enumerate(body):
        out[len(body) - 1 - index] = GLYPH_MIRROR.get(char, char)
    return "".join(out)


def extract_row_comment(line: str) -> str:
    if "cols c" not in line:
        return ""
    index = line.index("cols c")
    return line[index:].strip()


def extract_body(line: str) -> Optional[str]:
    stripped = line.strip()
    if len(stripped) == 10 and stripped[0] in "X.":
        return stripped
    parts = line.split()
    if len(parts) >= 2 and parts[1][0] in "X.":
        return parts[1]
    return None


def layer_rows(text: str, layer_name: str) -> List[str]:
    rows: List[str] = []
    active = False
    for line in text.splitlines():
        if line.startswith(f"layer {layer_name}"):
            active = True
            continue
        if active and line.startswith("layer "):
            break
        if not active:
            continue
        if extract_body(line) is not None:
            rows.append(line)
    return rows


def layer_bodies(text: str, layer_name: str) -> List[str]:
    return [extract_body(line) or "" for line in layer_rows(text, layer_name)]


def row_line(west: str, body: str, east: str, comment: str = "") -> str:
    suffix = f"  {comment}" if comment else ""
    return f"{west:<6}{body} {east}{suffix}"


def map_row(label: str) -> str:
    if label.startswith("GND"):
        if ":" in label:
            occurrence = int(label.split(":", 1)[1])
            return GND_ROWS[occurrence - 1]
        return "GND"
    return ROW_MAP[label]


def mirror_endpoint(token: str) -> str:
    match = re.match(r"^([A-Za-z0-9_:-]+)\.c(\d+)$", token)
    if match is None:
        raise ValueError(f"bad intent endpoint {token!r}")
    row = map_row(match.group(1))
    col = int(match.group(2))
    if 1 <= col <= 8:
        col = 9 - col
    return f"{row}.c{col}"


def mirror_intents(up_text: str) -> List[str]:
    lines = [
        "# scratch",
        "# Mirrored from up-side.vox.",
        "# labels: P20 pico, P19 side.",
        "",
        "# trace intents",
    ]
    in_block = False
    for raw in up_text.splitlines():
        if raw.strip() == "# trace intents":
            in_block = True
            continue
        if not in_block:
            continue
        if raw.startswith("# net "):
            _, _, rest = raw.partition("net ")
            name, _, endpoints = rest.partition(" ")
            mirrored = [mirror_endpoint(token) for token in endpoints.split()]
            lines.append(f"# net {name} {' '.join(mirrored)}")
            continue
        if raw.startswith("# disjoint "):
            lines.append(raw)
            continue
        if raw.startswith("# all planned"):
            lines.append(raw)
            break
    return lines


def build_pico_side(up_path: Path, out_path: Path) -> None:
    up_text = up_path.read_text(encoding="utf-8")
    base = layer_bodies(up_text, "base")
    trace = layer_bodies(up_text, "trace")
    trace_source_rows = layer_rows(up_text, "trace")
    if len(base) != 22 or len(trace) != 22:
        raise ValueError(
            f"expected 22 rows per layer, got base={len(base)} trace={len(trace)}"
        )

    lines = [
        "# Text voxel design for thermo Pico2W sensor HAT, pico-side variant.",
        "# UNIT_MM=2.54",
        "# Layer header: layer NAME (horizontal_offset, width_columns, height_rows)",
        "# Grid columns west to east: border, -8.89, -6.35, -3.81, -1.27, 1.27, 3.81, 6.35, 8.89, border",
        "# Rows north to south.",
        "# Legend: X=solid substrate, *=Pico pin pad, O=device leg pad, .=empty/air, a-z=embossed labels.",
        "# Trace tiles: |=vertical, -=horizontal, +=intersection.",
        "# Flat-side mount: same net topology as up-side.vox with traces/pads mirrored across X=0.",
        "# Print flat-side down; modules attach from the top (mounted upside down vs up-side).",
        "# Pico header: c1 = west (-8.89), c8 = east (8.89).",
        "",
        "layer base (6, 10, 22)",
    ]
    for index, body in enumerate(base):
        if index in {0, 21}:
            lines.append("      " + body)
            continue
        _, pico_west, _, pico_east = ROWS[index - 1]
        lines.append(row_line(pico_west, mirror_chars(body), pico_east))

    lines.extend(["", "layer trace (6, 10, 22)"])
    for index, body in enumerate(trace):
        if index in {0, 21}:
            lines.append("      " + body)
            continue
        up_west, pico_west, _, pico_east = ROWS[index - 1]
        trace_body = TRACE_CUSTOM.get(index, mirror_chars(body))
        comment_parts: List[str] = []
        if up_west in ROW_COMMENTS:
            comment_parts.append(ROW_COMMENTS[up_west])
        source_comment = extract_row_comment(trace_source_rows[index])
        if source_comment:
            comment_parts.append(mirror_col_comment(source_comment))
        lines.append(
            row_line(pico_west, trace_body, pico_east, "; ".join(comment_parts))
        )

    lines.extend(mirror_intents(up_text))
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    hat_dir = Path(__file__).resolve().parent
    build_pico_side(hat_dir / "up-side.vox", hat_dir / "pico-side.vox")
    print(f"ok wrote {hat_dir / 'pico-side.vox'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
