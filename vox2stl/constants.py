#!/usr/bin/env python3
"""Shared constants for vox2stl geometry, glyphs, and label tiles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

# Physical pitch of one text-grid cell.
DEFAULT_UNIT_MM = 2.54

# Trace width as a fraction of one grid cell.
DEFAULT_TRACE_WIDTH_FRAC = 0.72 * (0.72 / 0.88)

# Minimum no-copper gap between adjacent isolated features, in cell fractions.
DEFAULT_ADJACENT_ISOLATION_GAP_FRAC = 0.12

# Pico pin through-hole diameter as a fraction of one grid cell.
DEFAULT_PIN_HOLE_DIAMETER_FRAC = (1.10 * 0.66) / DEFAULT_UNIT_MM

# Device-leg through-hole diameter as a fraction of one grid cell.
DEFAULT_LEG_HOLE_DIAMETER_FRAC = 1.10 / DEFAULT_UNIT_MM

# Pico pin raised pad outside width as a fraction of one grid cell.
DEFAULT_PIN_OUTSIDE_FRAC = 0.72

# Device-leg raised pad outside width as a fraction of one grid cell.
DEFAULT_LEG_OUTSIDE_FRAC = 0.72

# Extra trace reach past tile centers to help slicers fuse neighboring tiles.
DEFAULT_TILE_OVERLAP_FRAC = 0.08

# Clearance from trace arms to through-hole voids, in cell fractions.
DEFAULT_TRACE_HOLE_CLEARANCE_FRAC = 0.04

# Debug grid-line width as a fraction of one grid cell.
DEFAULT_GRID_FRAC = 0.20

# Embossed label inset from tile edges, in cell fractions.
DEFAULT_LABEL_RECESS_FRAC = 0.04

# Embossed label height above the trace-layer base, in cell fractions.
DEFAULT_LABEL_HEIGHT_FRAC = 0.40

# Maximum triangles allowed for one pre-rendered letter tile.
DEFAULT_LABEL_TILE_MAX_TRIANGLES = 30000

# Raster field resolution used before meshing letter strokes.
DEFAULT_LABEL_RASTER_SIZE = 512

# Stroke width for Hershey letter centerlines, in cell fractions.
DEFAULT_LABEL_STROKE_FRAC = 0.20

# Number of blur passes used to smooth rasterized letter strokes.
DEFAULT_LABEL_BLUR_PASSES = 4

# Box-blur radius used per smoothing pass for letter strokes.
DEFAULT_LABEL_BLUR_RADIUS = 5

# Comfortable upper bound for welded mesh edges sharing one vertex.
DEFAULT_MAX_VERTEX_VALENCE = 20

# Directory containing persistent binary STL letter tile fragments.
LETTER_TILES_DIR = Path(__file__).resolve().parent / "tiles" / "letters"

# Trace width in millimeters.
DEFAULT_TRACE_WIDTH_MM = DEFAULT_TRACE_WIDTH_FRAC * DEFAULT_UNIT_MM

# Minimum no-copper gap in millimeters.
DEFAULT_ADJACENT_ISOLATION_GAP_MM = DEFAULT_ADJACENT_ISOLATION_GAP_FRAC * DEFAULT_UNIT_MM

# Pico pin raised pad outside width in millimeters.
DEFAULT_PAD_WIDTH_MM = DEFAULT_PIN_OUTSIDE_FRAC * DEFAULT_UNIT_MM

# Device-leg raised pad outside width in millimeters.
DEFAULT_DEVICE_PAD_WIDTH_MM = DEFAULT_LEG_OUTSIDE_FRAC * DEFAULT_UNIT_MM

# Pico pin through-hole diameter in millimeters.
DEFAULT_PIN_HOLE_DIAMETER_MM = DEFAULT_PIN_HOLE_DIAMETER_FRAC * DEFAULT_UNIT_MM

# Device-leg through-hole diameter in millimeters.
DEFAULT_DEVICE_HOLE_DIAMETER_MM = DEFAULT_LEG_HOLE_DIAMETER_FRAC * DEFAULT_UNIT_MM

# Trace overlap distance in millimeters.
DEFAULT_OVERLAP_MM = DEFAULT_TILE_OVERLAP_FRAC * DEFAULT_UNIT_MM

# Trace-to-through-hole clearance in millimeters.
DEFAULT_TRACE_HOLE_CLEARANCE_MM = DEFAULT_TRACE_HOLE_CLEARANCE_FRAC * DEFAULT_UNIT_MM

# Label inset from tile edges in millimeters.
DEFAULT_LABEL_RECESS_MM = DEFAULT_LABEL_RECESS_FRAC * DEFAULT_UNIT_MM

# Label height above the trace-layer base in millimeters.
DEFAULT_LABEL_HEIGHT_MM = DEFAULT_LABEL_HEIGHT_FRAC * DEFAULT_UNIT_MM

# Bottom Z coordinate of the substrate.
DEFAULT_BASE_Z0_MM = 0.0

# Top Z coordinate of the substrate.
DEFAULT_BASE_Z1_MM = 3.175

# Bottom Z coordinate for raised traces, pads, and labels.
DEFAULT_TRACE_Z0_MM = DEFAULT_BASE_Z1_MM

# Top Z coordinate for raised traces and pads.
DEFAULT_TRACE_Z1_MM = 6.350

# Debug grid-line width in millimeters.
DEFAULT_GRID_MM = DEFAULT_GRID_FRAC * DEFAULT_UNIT_MM

# Layer header parser for .vox files.
LAYER_HEADER_RE = re.compile(r"^layer\s+([A-Za-z0-9_-]+)\s+\((\d+),\s*(\d+),\s*(\d+)\)$")

# UNIT_MM metadata parser for .vox files.
UNIT_RE = re.compile(r"UNIT_MM\s*=\s*([0-9]+(?:\.[0-9]+)?)")

# Trace glyph alias parser for .vox files.
ALIAS_RE = re.compile(r"^alias\s+(\S)\s*->\s*(\S)\s*=\s*([A-Za-z0-9_:-]+)\s*$")

# Upper-left box drawing corner glyph.
BOX_UL = "\u250c"

# Upper-right box drawing corner glyph.
BOX_UR = "\u2510"

# Lower-left box drawing corner glyph.
BOX_LL = "\u2514"

# Lower-right box drawing corner glyph.
BOX_LR = "\u2518"

# Box drawing T junction with a right arm.
BOX_T_RIGHT = "\u251c"

# Box drawing T junction with a left arm.
BOX_T_LEFT = "\u2524"

# Box drawing T junction open downward.
BOX_T_DOWN = "\u252c"

# Box drawing T junction open upward.
BOX_T_UP = "\u2534"

# Box drawing four-way crossing glyph.
BOX_CROSS = "\u253c"

# Box drawing horizontal trace glyph.
BOX_H = "\u2500"

# Box drawing vertical trace glyph.
BOX_V = "\u2502"

# Pico pin pad glyph.
PIN_PAD_CHAR = "*"

# Device leg pad glyph.
LEG_PAD_CHAR = "O"

# Set of all pad glyphs.
PAD_CHARS: FrozenSet[str] = frozenset({PIN_PAD_CHAR, LEG_PAD_CHAR})

# Connection arms exposed by each trace glyph.
ARMS_BY_CHAR: Dict[str, FrozenSet[str]] = {
    "-": frozenset({"E", "W"}),
    "|": frozenset({"N", "S"}),
    "+": frozenset({"N", "E", "S", "W"}),
    BOX_UL: frozenset({"E", "S"}),
    BOX_UR: frozenset({"S", "W"}),
    BOX_LL: frozenset({"N", "E"}),
    BOX_LR: frozenset({"N", "W"}),
    BOX_T_RIGHT: frozenset({"N", "E", "S"}),
    BOX_T_LEFT: frozenset({"N", "S", "W"}),
    BOX_T_DOWN: frozenset({"E", "S", "W"}),
    BOX_T_UP: frozenset({"N", "E", "W"}),
    BOX_CROSS: frozenset({"N", "E", "S", "W"}),
    BOX_H: frozenset({"E", "W"}),
    BOX_V: frozenset({"N", "S"}),
}

# Opposite cardinal direction for neighbor connection checks.
OPPOSITE_DIRECTION: Dict[str, str] = {"N": "S", "E": "W", "S": "N", "W": "E"}


@dataclass(frozen=True)
class VoxAlias:
    source: str
    target: str
    net_name: str

SHORTHAND_DIRECT_CHARS: Dict[str, str] = {
    "<": BOX_T_LEFT,
    ">": BOX_T_RIGHT,
    "^": BOX_T_UP,
    "T": BOX_T_DOWN,
}

SHORTHAND_CORNER_CANDIDATES: Dict[str, Tuple[Tuple[str, FrozenSet[str]], ...]] = {
    "/": (
        (BOX_UL, ARMS_BY_CHAR[BOX_UL]),
        (BOX_LR, ARMS_BY_CHAR[BOX_LR]),
    ),
    "\\": (
        (BOX_UR, ARMS_BY_CHAR[BOX_UR]),
        (BOX_LL, ARMS_BY_CHAR[BOX_LL]),
    ),
}

ALL_DIRECTIONS: Tuple[str, ...] = ("N", "E", "S", "W")


def _split_line_ending(raw_line: str) -> Tuple[str, str]:
    if raw_line.endswith("\r\n"):
        return raw_line[:-2], "\r\n"
    if raw_line.endswith("\n"):
        return raw_line[:-1], "\n"
    if raw_line.endswith("\r"):
        return raw_line[:-1], "\r"
    return raw_line, ""


def parse_alias_line(line: str) -> Optional[VoxAlias]:
    match = ALIAS_RE.match(line)
    if match is None:
        return None
    return VoxAlias(source=match.group(1), target=match.group(2), net_name=match.group(3))


def parse_vox_aliases_text(text: str) -> Dict[str, VoxAlias]:
    aliases: Dict[str, VoxAlias] = {}
    for raw_line in text.splitlines():
        alias = parse_alias_line(raw_line.strip())
        if alias is not None:
            aliases[alias.source] = alias
    return aliases


def effective_trace_char(char: str, aliases: Mapping[str, VoxAlias]) -> str:
    alias = aliases.get(char)
    if alias is None:
        return SHORTHAND_DIRECT_CHARS.get(char, char)
    return alias.target


def trace_arms(char: str, aliases: Mapping[str, VoxAlias]) -> FrozenSet[str]:
    effective = effective_trace_char(char, aliases)
    if effective in PAD_CHARS:
        return frozenset(ALL_DIRECTIONS)
    return ARMS_BY_CHAR.get(effective, frozenset())


def _possible_arms(char: str, aliases: Mapping[str, VoxAlias]) -> FrozenSet[str]:
    effective = effective_trace_char(char, aliases)
    direct = SHORTHAND_DIRECT_CHARS.get(char)
    if direct is not None:
        return ARMS_BY_CHAR[direct]
    if effective in PAD_CHARS:
        return frozenset(ALL_DIRECTIONS)
    arms = ARMS_BY_CHAR.get(effective)
    if arms is not None:
        return arms
    candidates = SHORTHAND_CORNER_CANDIDATES.get(char)
    if candidates is None:
        return frozenset()
    possible: set[str] = set()
    for _, candidate_arms in candidates:
        possible.update(candidate_arms)
    return frozenset(possible)


def _neighbor_char(grid: Sequence[str], row_index: int, col_index: int, direction: str) -> str:
    next_row = row_index
    next_col = col_index
    if direction == "N":
        next_row -= 1
    elif direction == "S":
        next_row += 1
    elif direction == "E":
        next_col += 1
    elif direction == "W":
        next_col -= 1
    else:
        raise ValueError(f"unknown direction {direction!r}")
    if next_row < 0 or next_row >= len(grid):
        return "."
    if next_col < 0 or next_col >= len(grid[next_row]):
        return "."
    return grid[next_row][next_col]


def _best_corner_replacement(
    grid: Sequence[str],
    row_index: int,
    col_index: int,
    char: str,
    aliases: Mapping[str, VoxAlias],
) -> Optional[str]:
    candidates = SHORTHAND_CORNER_CANDIDATES.get(char)
    if candidates is None:
        return None

    best_char: Optional[str] = None
    best_score = 0
    tied = False
    for candidate_char, arms in candidates:
        score = 0
        for direction in ALL_DIRECTIONS:
            neighbor = _neighbor_char(grid, row_index, col_index, direction)
            neighbor_arms = _possible_arms(neighbor, aliases)
            if direction in arms and OPPOSITE_DIRECTION[direction] in neighbor_arms:
                score += 1
        if score > best_score:
            best_char = candidate_char
            best_score = score
            tied = False
        elif score == best_score and score > 0:
            tied = True
    if best_score == 0 or tied:
        return None
    return best_char


def _correct_layer_rows(
    rows: Sequence[str],
    offset: int,
    width: int,
    aliases: Mapping[str, VoxAlias],
) -> List[str]:
    end = offset + width
    grid = [row.ljust(end)[offset:end] for row in rows]
    corrected: List[str] = []
    for row_index, row in enumerate(rows):
        chars = list(row.ljust(end))
        for absolute_col in range(offset, end):
            col_index = absolute_col - offset
            char = chars[absolute_col]
            replacement = SHORTHAND_DIRECT_CHARS.get(char)
            if replacement is None:
                replacement = _best_corner_replacement(grid, row_index, col_index, char, aliases)
            if replacement is None and char == " ":
                replacement = "."
            if replacement is not None:
                chars[absolute_col] = replacement
        corrected.append("".join(chars))
    return corrected


def correct_vox_shorthand_text(text: str) -> str:
    """Return .vox text with ASCII trace shorthand normalized in layer rows."""

    split_lines = [_split_line_ending(raw_line) for raw_line in text.splitlines(keepends=True)]
    lines = [line for line, _ in split_lines]
    endings = [ending for _, ending in split_lines]
    aliases = parse_vox_aliases_text(text)
    layers: List[Tuple[int, int, List[int]]] = []
    current_offset: Optional[int] = None
    current_width: Optional[int] = None
    current_rows: List[int] = []

    def finish_layer() -> None:
        nonlocal current_offset, current_width, current_rows
        if current_offset is not None and current_width is not None and current_rows:
            layers.append((current_offset, current_width, current_rows))
        current_offset = None
        current_width = None
        current_rows = []

    for line_index, line in enumerate(lines):
        if not line or line.startswith("#"):
            continue
        if parse_alias_line(line.strip()) is not None:
            continue
        match = LAYER_HEADER_RE.match(line)
        if match:
            finish_layer()
            current_offset = int(match.group(2))
            current_width = int(match.group(3))
            continue
        if line.startswith("layer "):
            finish_layer()
            continue
        if current_offset is not None and current_width is not None:
            current_rows.append(line_index)

    finish_layer()

    for offset, width, row_indexes in layers:
        corrected_rows = _correct_layer_rows(
            [lines[index] for index in row_indexes],
            offset,
            width,
            aliases,
        )
        for line_index, corrected_row in zip(row_indexes, corrected_rows):
            lines[line_index] = corrected_row

    return "".join(line + ending for line, ending in zip(lines, endings))
