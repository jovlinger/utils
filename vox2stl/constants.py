#!/usr/bin/env python3
"""Shared constants for vox2stl geometry, glyphs, and label tiles."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from voxconf import VoxProfile, load_config

# Default per-layer rendering mode for lowercase letter cells.
DEFAULT_LETTER_STYLE = "positive"
LETTER_STYLES: FrozenSet[str] = frozenset({"positive", "negative"})

# Directory containing persistent binary STL letter tile fragments.
LETTER_TILES_DIR = Path(__file__).resolve().parent / "tiles" / "letters"

# Pickled dictionary of lazily rendered naive and ligature tile meshes.
TILE_CACHE_PATH = Path(__file__).resolve().parent / "tiles" / "tile_cache.pickle"


@dataclass(frozen=True)
class LayerHeader:
    name: str
    offset: int
    width: int
    height: int
    layer_thickness_mm: float
    letter_style: str


LAYER_POSITIONAL_KEYS: Tuple[str, str, str] = (
    "horizontal_offset",
    "width_columns",
    "height_rows",
)
LAYER_KEY_ALIASES: Mapping[str, str] = {
    "offset": "horizontal_offset",
    "width": "width_columns",
    "height": "height_rows",
}

def _apply_profile(profile: VoxProfile) -> None:
    global DEFAULT_UNIT_MM
    global DEFAULT_TRACE_WIDTH_FRAC
    global DEFAULT_ADJACENT_ISOLATION_GAP_FRAC
    global DEFAULT_PIN_OUTSIDE_FRAC
    global DEFAULT_LEG_OUTSIDE_FRAC
    global DEFAULT_TILE_OVERLAP_FRAC
    global DEFAULT_COND_LIG_FRAC
    global DEFAULT_ISOL_LIG_FRAC
    global DEFAULT_TRACE_HOLE_CLEARANCE_FRAC
    global DEFAULT_GRID_FRAC
    global DEFAULT_HOLE_OVAL_MINOR_FRAC
    global DEFAULT_HOLE_OVAL_BAND_MM
    global DEFAULT_HOLE_OVAL_Z_FRACS
    global HOLE_VOID_GRID_DIVISOR
    global DEFAULT_LABEL_RECESS_FRAC
    global DEFAULT_LABEL_HEIGHT_FRAC
    global DEFAULT_LABEL_TILE_MAX_TRIANGLES
    global DEFAULT_LABEL_RASTER_SIZE
    global DEFAULT_LABEL_STROKE_FRAC
    global DEFAULT_LABEL_BLUR_PASSES
    global DEFAULT_LABEL_BLUR_RADIUS
    global DEFAULT_MAX_VERTEX_VALENCE
    global DEFAULT_TRACE_WIDTH_MM
    global DEFAULT_ADJACENT_ISOLATION_GAP_MM
    global DEFAULT_PAD_WIDTH_MM
    global DEFAULT_DEVICE_PAD_WIDTH_MM
    global DEFAULT_PIN_HOLE_DIAMETER_MM
    global DEFAULT_DEVICE_HOLE_DIAMETER_MM
    global DEFAULT_OVERLAP_MM
    global DEFAULT_COND_LIG_MM
    global DEFAULT_ISOL_LIG_MM
    global DEFAULT_TRACE_HOLE_CLEARANCE_MM
    global DEFAULT_LABEL_RECESS_MM
    global DEFAULT_LABEL_HEIGHT_MM
    global DEFAULT_LAYER_THICKNESS_MM
    global DEFAULT_BASE_Z0_MM
    global DEFAULT_BASE_Z1_MM
    global DEFAULT_TRACE_Z0_MM
    global DEFAULT_TRACE_Z1_MM
    global DEFAULT_GRID_MM

    DEFAULT_UNIT_MM = profile.unit_mm
    DEFAULT_TRACE_WIDTH_FRAC = profile.trace_width_frac
    DEFAULT_ADJACENT_ISOLATION_GAP_FRAC = profile.adjacent_isolation_gap_frac
    DEFAULT_PIN_OUTSIDE_FRAC = profile.pin_outside_frac
    DEFAULT_LEG_OUTSIDE_FRAC = profile.leg_outside_frac
    DEFAULT_TILE_OVERLAP_FRAC = profile.tile_overlap_frac
    DEFAULT_COND_LIG_FRAC = profile.cond_lig_frac
    DEFAULT_ISOL_LIG_FRAC = profile.isol_lig_frac
    DEFAULT_TRACE_HOLE_CLEARANCE_FRAC = profile.trace_hole_clearance_frac
    DEFAULT_GRID_FRAC = profile.grid_frac
    DEFAULT_HOLE_OVAL_MINOR_FRAC = profile.hole_oval_minor_frac
    DEFAULT_HOLE_OVAL_BAND_MM = profile.hole_oval_band_mm
    DEFAULT_HOLE_OVAL_Z_FRACS = profile.hole_oval_z_fracs
    HOLE_VOID_GRID_DIVISOR = profile.hole_void_grid_divisor
    DEFAULT_LABEL_RECESS_FRAC = profile.label_recess_frac
    DEFAULT_LABEL_HEIGHT_FRAC = profile.label_height_frac
    DEFAULT_LABEL_TILE_MAX_TRIANGLES = profile.label_tile_max_triangles
    DEFAULT_LABEL_RASTER_SIZE = profile.label_raster_size
    DEFAULT_LABEL_STROKE_FRAC = profile.label_stroke_frac
    DEFAULT_LABEL_BLUR_PASSES = profile.label_blur_passes
    DEFAULT_LABEL_BLUR_RADIUS = profile.label_blur_radius
    DEFAULT_MAX_VERTEX_VALENCE = profile.max_vertex_valence
    DEFAULT_TRACE_WIDTH_MM = profile.trace_width_mm
    DEFAULT_ADJACENT_ISOLATION_GAP_MM = profile.adjacent_isolation_gap_mm
    DEFAULT_PAD_WIDTH_MM = profile.pad_width_mm
    DEFAULT_DEVICE_PAD_WIDTH_MM = profile.device_pad_width_mm
    DEFAULT_PIN_HOLE_DIAMETER_MM = profile.pin_hole_diameter_mm
    DEFAULT_DEVICE_HOLE_DIAMETER_MM = profile.device_hole_diameter_mm
    DEFAULT_OVERLAP_MM = profile.overlap_mm
    DEFAULT_COND_LIG_MM = profile.cond_lig_mm
    DEFAULT_ISOL_LIG_MM = profile.isol_lig_mm
    DEFAULT_TRACE_HOLE_CLEARANCE_MM = profile.trace_hole_clearance_mm
    DEFAULT_LABEL_RECESS_MM = profile.label_recess_mm
    DEFAULT_LABEL_HEIGHT_MM = profile.label_height_mm
    DEFAULT_LAYER_THICKNESS_MM = profile.layer_thickness_mm
    DEFAULT_BASE_Z0_MM = profile.base_z0_mm
    DEFAULT_BASE_Z1_MM = profile.resolved_base_z1_mm
    DEFAULT_TRACE_Z0_MM = profile.resolved_trace_z0_mm
    DEFAULT_TRACE_Z1_MM = profile.resolved_trace_z1_mm
    DEFAULT_GRID_MM = profile.grid_mm


# Physical pitch of one text-grid cell.
DEFAULT_UNIT_MM: float
DEFAULT_TRACE_WIDTH_FRAC: float
DEFAULT_ADJACENT_ISOLATION_GAP_FRAC: float
DEFAULT_PIN_OUTSIDE_FRAC: float
DEFAULT_LEG_OUTSIDE_FRAC: float
DEFAULT_TILE_OVERLAP_FRAC: float
DEFAULT_COND_LIG_FRAC: float
DEFAULT_ISOL_LIG_FRAC: float
DEFAULT_TRACE_HOLE_CLEARANCE_FRAC: float
DEFAULT_GRID_FRAC: float
DEFAULT_HOLE_OVAL_MINOR_FRAC: float
DEFAULT_HOLE_OVAL_BAND_MM: float
DEFAULT_HOLE_OVAL_Z_FRACS: Tuple[float, ...]
HOLE_VOID_GRID_DIVISOR: int
DEFAULT_LABEL_RECESS_FRAC: float
DEFAULT_LABEL_HEIGHT_FRAC: float
DEFAULT_LABEL_TILE_MAX_TRIANGLES: int
DEFAULT_LABEL_RASTER_SIZE: int
DEFAULT_LABEL_STROKE_FRAC: float
DEFAULT_LABEL_BLUR_PASSES: int
DEFAULT_LABEL_BLUR_RADIUS: int
DEFAULT_MAX_VERTEX_VALENCE: int
DEFAULT_TRACE_WIDTH_MM: float
DEFAULT_ADJACENT_ISOLATION_GAP_MM: float
DEFAULT_PAD_WIDTH_MM: float
DEFAULT_DEVICE_PAD_WIDTH_MM: float
DEFAULT_PIN_HOLE_DIAMETER_MM: float
DEFAULT_DEVICE_HOLE_DIAMETER_MM: float
DEFAULT_OVERLAP_MM: float
DEFAULT_COND_LIG_MM: float
DEFAULT_ISOL_LIG_MM: float
DEFAULT_TRACE_HOLE_CLEARANCE_MM: float
DEFAULT_LABEL_RECESS_MM: float
DEFAULT_LABEL_HEIGHT_MM: float
DEFAULT_LAYER_THICKNESS_MM: float
DEFAULT_BASE_Z0_MM: float
DEFAULT_BASE_Z1_MM: float
DEFAULT_TRACE_Z0_MM: float
DEFAULT_TRACE_Z1_MM: float
DEFAULT_GRID_MM: float

_apply_profile(load_config("default"))

# Layer header parser for .vox files.
LAYER_HEADER_RE = re.compile(r"^layer\s+([A-Za-z0-9_-]+)\s*\((.*)\)$")

# UNIT_MM metadata parser for .vox files.
UNIT_RE = re.compile(r"UNIT_MM\s*=\s*([0-9]+(?:\.[0-9]+)?)")

# Trace glyph alias parser for .vox files.
ALIAS_RE = re.compile(r"^alias\s+(\S)\s*->\s*(\S)\s*=\s*([A-Za-z0-9_:-]+)\s*$")


def _parse_positive_int(raw_value: str, key: str) -> int:
    if not raw_value.isdigit():
        raise ValueError(f"{key} must be a non-negative integer, got {raw_value!r}")
    return int(raw_value)


def _parse_positive_float(raw_value: str, key: str) -> float:
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{key} must be a number, got {raw_value!r}") from exc
    if value <= 0.0:
        raise ValueError(f"{key} must be positive, got {raw_value!r}")
    return value


def _parse_letter_style(raw_value: str) -> str:
    value = raw_value.strip().lower()
    if value not in LETTER_STYLES:
        allowed = ", ".join(sorted(LETTER_STYLES))
        raise ValueError(f"letter_style must be one of {allowed}, got {raw_value!r}")
    return value


def parse_layer_header(line: str) -> Optional[LayerHeader]:
    match = LAYER_HEADER_RE.match(line)
    if match is None:
        return None

    name = match.group(1)
    body = match.group(2).strip()
    if not body:
        raise ValueError("layer header has no arguments")

    values: Dict[str, str] = {}
    positional_index = 0
    saw_keyword = False
    for raw_part in body.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError("layer header contains an empty argument")
        if "=" in part:
            saw_keyword = True
            raw_key, raw_value = part.split("=", 1)
            key = LAYER_KEY_ALIASES.get(raw_key.strip(), raw_key.strip())
            value = raw_value.strip()
        else:
            if saw_keyword:
                raise ValueError("positional layer arguments must come before keyword arguments")
            if positional_index >= len(LAYER_POSITIONAL_KEYS):
                raise ValueError(f"unexpected positional layer argument {part!r}")
            key = LAYER_POSITIONAL_KEYS[positional_index]
            value = part
            positional_index += 1
        if key in values:
            raise ValueError(f"duplicate layer argument {key!r}")
        if key not in set(LAYER_POSITIONAL_KEYS) | {"layer_thickness_mm", "letter_style"}:
            raise ValueError(f"unknown layer argument {key!r}")
        values[key] = value

    missing = [key for key in LAYER_POSITIONAL_KEYS if key not in values]
    if missing:
        raise ValueError(f"missing layer argument(s): {', '.join(missing)}")

    return LayerHeader(
        name=name,
        offset=_parse_positive_int(values["horizontal_offset"], "horizontal_offset"),
        width=_parse_positive_int(values["width_columns"], "width_columns"),
        height=_parse_positive_int(values["height_rows"], "height_rows"),
        layer_thickness_mm=_parse_positive_float(
            values.get("layer_thickness_mm", str(DEFAULT_LAYER_THICKNESS_MM)),
            "layer_thickness_mm",
        ),
        letter_style=_parse_letter_style(values.get("letter_style", DEFAULT_LETTER_STYLE)),
    )

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
        header = parse_layer_header(line)
        if header is not None:
            finish_layer()
            current_offset = header.offset
            current_width = header.width
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
