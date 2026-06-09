#!/usr/bin/env python3
"""Shared constants for vox2stl geometry, glyphs, and label tiles."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, FrozenSet

# Physical pitch of one text-grid cell.
DEFAULT_UNIT_MM = 2.54

# Trace width as a fraction of one grid cell.
DEFAULT_TRACE_WIDTH_FRAC = 0.72

# Minimum no-copper gap between adjacent isolated features, in cell fractions.
DEFAULT_ADJACENT_ISOLATION_GAP_FRAC = 0.12

# Pico pin through-hole diameter as a fraction of one grid cell.
DEFAULT_PIN_HOLE_DIAMETER_FRAC = 1.10 / DEFAULT_UNIT_MM

# Device-leg through-hole diameter as a fraction of one grid cell.
DEFAULT_LEG_HOLE_DIAMETER_FRAC = DEFAULT_PIN_HOLE_DIAMETER_FRAC * 1.25

# Pico pin raised pad outside width as a fraction of one grid cell.
DEFAULT_PIN_OUTSIDE_FRAC = 0.88

# Device-leg raised pad outside width as a fraction of one grid cell.
DEFAULT_LEG_OUTSIDE_FRAC = 0.88

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

# Upper-left box drawing corner glyph.
BOX_UL = "\u250c"

# Upper-right box drawing corner glyph.
BOX_UR = "\u2510"

# Lower-left box drawing corner glyph.
BOX_LL = "\u2514"

# Lower-right box drawing corner glyph.
BOX_LR = "\u2518"

# Box drawing T junction open to the left side.
BOX_T_LEFT = "\u251c"

# Box drawing T junction open to the right side.
BOX_T_RIGHT = "\u2524"

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
    BOX_T_LEFT: frozenset({"N", "E", "S"}),
    BOX_T_RIGHT: frozenset({"N", "S", "W"}),
    BOX_T_DOWN: frozenset({"E", "S", "W"}),
    BOX_T_UP: frozenset({"N", "E", "W"}),
    BOX_CROSS: frozenset({"N", "E", "S", "W"}),
    BOX_H: frozenset({"E", "W"}),
    BOX_V: frozenset({"N", "S"}),
}

# Opposite cardinal direction for neighbor connection checks.
OPPOSITE_DIRECTION: Dict[str, str] = {"N": "S", "E": "W", "S": "N", "W": "E"}
