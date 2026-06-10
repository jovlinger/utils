#!/usr/bin/env python3
"""Convert a text voxel layer to an ASCII STL feature mesh."""

from __future__ import annotations

import argparse
import math
import re
import struct
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from constants import (
    ARMS_BY_CHAR,
    BOX_CROSS,
    BOX_H,
    BOX_LL,
    BOX_LR,
    BOX_T_DOWN,
    BOX_T_LEFT,
    BOX_T_RIGHT,
    BOX_T_UP,
    BOX_UL,
    BOX_UR,
    BOX_V,
    DEFAULT_ADJACENT_ISOLATION_GAP_FRAC,
    DEFAULT_ADJACENT_ISOLATION_GAP_MM,
    DEFAULT_BASE_Z0_MM,
    DEFAULT_BASE_Z1_MM,
    DEFAULT_DEVICE_HOLE_DIAMETER_MM,
    DEFAULT_DEVICE_PAD_WIDTH_MM,
    DEFAULT_GRID_MM,
    DEFAULT_GRID_FRAC,
    DEFAULT_LABEL_BLUR_PASSES,
    DEFAULT_LABEL_BLUR_RADIUS,
    DEFAULT_LABEL_HEIGHT_FRAC,
    DEFAULT_LABEL_HEIGHT_MM,
    DEFAULT_LABEL_RASTER_SIZE,
    DEFAULT_LABEL_RECESS_FRAC,
    DEFAULT_LABEL_RECESS_MM,
    DEFAULT_LABEL_STROKE_FRAC,
    DEFAULT_LABEL_TILE_MAX_TRIANGLES,
    DEFAULT_LEG_HOLE_DIAMETER_FRAC,
    DEFAULT_LEG_OUTSIDE_FRAC,
    DEFAULT_MAX_VERTEX_VALENCE,
    DEFAULT_OVERLAP_MM,
    DEFAULT_PIN_HOLE_DIAMETER_FRAC,
    DEFAULT_PAD_WIDTH_MM,
    DEFAULT_PIN_HOLE_DIAMETER_MM,
    DEFAULT_PIN_OUTSIDE_FRAC,
    DEFAULT_TILE_OVERLAP_FRAC,
    DEFAULT_TRACE_HOLE_CLEARANCE_FRAC,
    DEFAULT_TRACE_HOLE_CLEARANCE_MM,
    DEFAULT_TRACE_WIDTH_FRAC,
    DEFAULT_TRACE_WIDTH_MM,
    DEFAULT_TRACE_Z0_MM,
    DEFAULT_TRACE_Z1_MM,
    DEFAULT_UNIT_MM,
    LAYER_HEADER_RE,
    LEG_PAD_CHAR,
    LETTER_TILES_DIR,
    OPPOSITE_DIRECTION,
    PAD_CHARS,
    PIN_PAD_CHAR,
    SHORTHAND_DIRECT_CHARS,
    parse_alias_line,
    UNIT_RE,
)
from letter_mesh import generate_letter_tile_triangles

Vec3 = Tuple[float, float, float]
Tri = Tuple[Vec3, Vec3, Vec3]


@dataclass(frozen=True)
class Layer:
    name: str
    offset: int
    width: int
    height: int
    rows: Tuple[str, ...]


@dataclass(frozen=True)
class BoxSolid:
    x0: float
    y0: float
    x1: float
    y1: float
    z0: float
    z1: float


@dataclass(frozen=True)
class Hole:
    x: float
    y: float
    radius: float


@dataclass(frozen=True)
class RenderConfig:
    unit_mm: float = DEFAULT_UNIT_MM
    trace_width_mm: float = DEFAULT_TRACE_WIDTH_MM
    pad_width_mm: float = DEFAULT_PAD_WIDTH_MM
    device_pad_width_mm: float = DEFAULT_DEVICE_PAD_WIDTH_MM
    pin_hole_diameter_mm: float = DEFAULT_PIN_HOLE_DIAMETER_MM
    device_hole_diameter_mm: float = DEFAULT_DEVICE_HOLE_DIAMETER_MM
    adjacent_isolation_gap_mm: float = DEFAULT_ADJACENT_ISOLATION_GAP_MM
    overlap_mm: float = DEFAULT_OVERLAP_MM
    trace_hole_clearance_mm: float = DEFAULT_TRACE_HOLE_CLEARANCE_MM
    label_recess_mm: float = DEFAULT_LABEL_RECESS_MM
    label_height_mm: float = DEFAULT_LABEL_HEIGHT_MM
    base_z0_mm: float = DEFAULT_BASE_Z0_MM
    base_z1_mm: float = DEFAULT_BASE_Z1_MM
    trace_z0_mm: float = DEFAULT_TRACE_Z0_MM
    trace_z1_mm: float = DEFAULT_TRACE_Z1_MM
    grid_mm: float = DEFAULT_GRID_MM
    origin_x_mm: float = 0.0
    origin_y_mm: float = 0.0
    include_pads: bool = True


class Mesh:
    def __init__(self) -> None:
        self.triangles: List[Tri] = []

    def extend(self, tris: Iterable[Tri]) -> None:
        self.triangles.extend(tris)

    def write_ascii_stl(self, path: Path, name: str) -> None:
        lines: List[str] = [f"solid {name}"]
        for a, b, c in self.triangles:
            normal = normal_for_tri(a, b, c)
            lines.append(f"  facet normal {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}")
            lines.append("    outer loop")
            for vertex in (a, b, c):
                lines.append(f"      vertex {vertex[0]:.6f} {vertex[1]:.6f} {vertex[2]:.6f}")
            lines.append("    endloop")
            lines.append("  endfacet")
        lines.append(f"endsolid {name}")
        path.write_text("\n".join(lines) + "\n", encoding="ascii")


def normal_for_tri(a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length == 0.0:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def box_tris(box: BoxSolid) -> List[Tri]:
    pts: List[Vec3] = [
        (box.x0, box.y0, box.z0),
        (box.x1, box.y0, box.z0),
        (box.x1, box.y1, box.z0),
        (box.x0, box.y1, box.z0),
        (box.x0, box.y0, box.z1),
        (box.x1, box.y0, box.z1),
        (box.x1, box.y1, box.z1),
        (box.x0, box.y1, box.z1),
    ]
    faces: List[Tuple[int, int, int]] = [
        (0, 1, 2),
        (0, 2, 3),
        (4, 6, 5),
        (4, 7, 6),
        (0, 4, 5),
        (0, 5, 1),
        (1, 5, 6),
        (1, 6, 2),
        (2, 6, 7),
        (2, 7, 3),
        (3, 7, 4),
        (3, 4, 0),
    ]
    return [(pts[i], pts[j], pts[k]) for i, j, k in faces]


def cylinder_wall_tris(
    cx: float, cy: float, radius: float, z0: float, z1: float, segments: int = 20
) -> List[Tri]:
    tris: List[Tri] = []
    for index in range(segments):
        a0 = 2.0 * math.pi * index / segments
        a1 = 2.0 * math.pi * (index + 1) / segments
        x0 = cx + radius * math.cos(a0)
        y0 = cy + radius * math.sin(a0)
        x1 = cx + radius * math.cos(a1)
        y1 = cy + radius * math.sin(a1)
        low0: Vec3 = (x0, y0, z0)
        low1: Vec3 = (x1, y1, z0)
        high0: Vec3 = (x0, y0, z1)
        high1: Vec3 = (x1, y1, z1)
        tris.append((low0, low1, high1))
        tris.append((low0, high1, high0))
    return tris


def inside_hole(x: float, y: float, holes: Sequence[Hole]) -> bool:
    for hole in holes:
        dx = x - hole.x
        dy = y - hole.y
        if dx * dx + dy * dy <= hole.radius * hole.radius:
            return True
    return False


def box_intersects_hole(box: BoxSolid, hole: Hole) -> bool:
    nearest_x = min(max(hole.x, box.x0), box.x1)
    nearest_y = min(max(hole.y, box.y0), box.y1)
    dx = nearest_x - hole.x
    dy = nearest_y - hole.y
    return dx * dx + dy * dy <= hole.radius * hole.radius


def box_intersects_any_hole(box: BoxSolid, holes: Sequence[Hole]) -> bool:
    return any(box_intersects_hole(box, hole) for hole in holes)


def plate_with_holes_tris(box: BoxSolid, holes: Sequence[Hole], grid_mm: float) -> List[Tri]:
    tris: List[Tri] = []
    x = box.x0
    while x < box.x1 - 1e-6:
        xn = min(x + grid_mm, box.x1)
        y = box.y0
        while y < box.y1 - 1e-6:
            yn = min(y + grid_mm, box.y1)
            cx = (x + xn) * 0.5
            cy = (y + yn) * 0.5
            if not inside_hole(cx, cy, holes):
                tris.extend(
                    [
                        ((x, y, box.z0), (xn, y, box.z0), (xn, yn, box.z0)),
                        ((x, y, box.z0), (xn, yn, box.z0), (x, yn, box.z0)),
                        ((x, y, box.z1), (xn, yn, box.z1), (xn, y, box.z1)),
                        ((x, y, box.z1), (x, yn, box.z1), (xn, yn, box.z1)),
                    ]
                )
            y = yn
        x = xn

    for hole in holes:
        if box_contains_hole(box, hole):
            tris.extend(cylinder_wall_tris(hole.x, hole.y, hole.radius, box.z0, box.z1))

    def edge_strip(
        fixed_coord: float,
        var_start: float,
        var_end: float,
        axis: str,
        outward: str,
    ) -> None:
        var = var_start
        while var < var_end - 1e-6:
            vnext = min(var + grid_mm, var_end)
            mid = (var + vnext) * 0.5
            if axis == "x":
                cx, cy = fixed_coord, mid
            else:
                cx, cy = mid, fixed_coord
            if inside_hole(cx, cy, holes):
                var = vnext
                continue
            if axis == "x":
                if outward == "neg":
                    tris.extend(
                        [
                            ((fixed_coord, var, box.z0), (fixed_coord, vnext, box.z0), (fixed_coord, vnext, box.z1)),
                            ((fixed_coord, var, box.z0), (fixed_coord, vnext, box.z1), (fixed_coord, var, box.z1)),
                        ]
                    )
                else:
                    tris.extend(
                        [
                            ((fixed_coord, var, box.z1), (fixed_coord, vnext, box.z1), (fixed_coord, vnext, box.z0)),
                            ((fixed_coord, var, box.z1), (fixed_coord, vnext, box.z0), (fixed_coord, var, box.z0)),
                        ]
                    )
            elif outward == "neg":
                tris.extend(
                    [
                        ((var, fixed_coord, box.z0), (vnext, fixed_coord, box.z0), (vnext, fixed_coord, box.z1)),
                        ((var, fixed_coord, box.z0), (vnext, fixed_coord, box.z1), (var, fixed_coord, box.z1)),
                    ]
                )
            else:
                tris.extend(
                    [
                        ((var, fixed_coord, box.z1), (vnext, fixed_coord, box.z1), (vnext, fixed_coord, box.z0)),
                        ((var, fixed_coord, box.z1), (vnext, fixed_coord, box.z0), (var, fixed_coord, box.z0)),
                    ]
                )
            var = vnext

    edge_strip(box.x0, box.y0, box.y1, "x", "neg")
    edge_strip(box.x1, box.y0, box.y1, "x", "pos")
    edge_strip(box.y0, box.x0, box.x1, "y", "neg")
    edge_strip(box.y1, box.x0, box.x1, "y", "pos")
    return tris


def read_layers(path: Path) -> Dict[str, Layer]:
    layers: Dict[str, Layer] = {}
    aliases: Dict[str, str] = {}
    current_name: Optional[str] = None
    current_offset = 0
    current_width = 0
    current_height = 0
    current_rows: List[str] = []

    def finish_layer() -> None:
        nonlocal current_name, current_offset, current_width, current_height, current_rows
        if current_name is None:
            return
        if len(current_rows) != current_height:
            raise ValueError(
                f"{path}: layer {current_name!r} has {len(current_rows)} rows; "
                f"expected {current_height}"
            )
        layers[current_name] = Layer(
            name=current_name,
            offset=current_offset,
            width=current_width,
            height=current_height,
            rows=tuple(current_rows),
        )
        current_name = None
        current_rows = []

    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        alias = parse_alias_line(line.strip())
        if alias is not None:
            aliases[alias.source] = alias.target
            continue
        match = LAYER_HEADER_RE.match(line)
        if match:
            finish_layer()
            current_name = match.group(1)
            if current_name in layers:
                raise ValueError(f"{path}:{line_no}: duplicate layer {current_name!r}")
            current_offset = int(match.group(2))
            current_width = int(match.group(3))
            current_height = int(match.group(4))
            current_rows = []
            continue
        if line.startswith("layer "):
            raise ValueError(f"{path}:{line_no}: invalid layer header")
        if current_name is None:
            raise ValueError(f"{path}:{line_no}: content before first layer")
        end = current_offset + current_width
        chars = list(line.ljust(end))
        for absolute_col in range(current_offset, end):
            char = aliases.get(chars[absolute_col], chars[absolute_col])
            chars[absolute_col] = SHORTHAND_DIRECT_CHARS.get(char, char)
        current_rows.append("".join(chars))

    finish_layer()
    return layers


def unit_from_file(path: Path) -> Optional[float]:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        match = UNIT_RE.search(raw_line)
        if match:
            return float(match.group(1))
    return None


def layer_window(layer: Layer, row: str) -> str:
    end = layer.offset + layer.width
    return row.ljust(end)[layer.offset:end]


def layer_bounds(layer: Layer, config: RenderConfig, z0: float, z1: float) -> BoxSolid:
    min_x = config.origin_x_mm - layer.width * config.unit_mm * 0.5
    max_x = config.origin_x_mm + layer.width * config.unit_mm * 0.5
    min_y = config.origin_y_mm - layer.height * config.unit_mm * 0.5
    max_y = config.origin_y_mm + layer.height * config.unit_mm * 0.5
    return BoxSolid(min_x, min_y, max_x, max_y, z0, z1)


def cell_center(layer: Layer, row_index: int, col_index: int, config: RenderConfig) -> Tuple[float, float]:
    x = (col_index - (layer.width - 1) * 0.5) * config.unit_mm + config.origin_x_mm
    y = ((layer.height - 1) * 0.5 - row_index) * config.unit_mm + config.origin_y_mm
    return x, y


def isolated_width(width: float, config: RenderConfig) -> float:
    return min(width, config.unit_mm - config.adjacent_isolation_gap_mm)


def trace_width(config: RenderConfig) -> float:
    return isolated_width(config.trace_width_mm, config)


def pad_width(char: str, config: RenderConfig) -> float:
    raw_width = config.pad_width_mm if char == PIN_PAD_CHAR else config.device_pad_width_mm
    return isolated_width(raw_width, config)


def square_box(cx: float, cy: float, width: float, z0: float, z1: float) -> BoxSolid:
    half = width * 0.5
    return BoxSolid(cx - half, cy - half, cx + half, cy + half, z0, z1)


def is_label_char(char: str) -> bool:
    return "a" <= char <= "z"


def write_binary_stl(path: Path, triangles: Sequence[Tri], name: str = "tile") -> None:
    header = f"vox2stl letter tile {name}".encode("ascii", errors="ignore")[:80]
    header = header.ljust(80, b" ")
    payload = bytearray(header)
    payload.extend(struct.pack("<I", len(triangles)))
    for a, b, c in triangles:
        normal = normal_for_tri(a, b, c)
        payload.extend(struct.pack("<3f", normal[0], normal[1], normal[2]))
        payload.extend(struct.pack("<3f", a[0], a[1], a[2]))
        payload.extend(struct.pack("<3f", b[0], b[1], b[2]))
        payload.extend(struct.pack("<3f", c[0], c[1], c[2]))
        payload.extend(struct.pack("<H", 0))
    path.write_bytes(payload)


def read_binary_stl_bytes(data: bytes, source: str = "binary STL") -> List[Tri]:
    if len(data) < 84:
        raise ValueError(f"{source}: binary STL too short")
    triangle_count = struct.unpack_from("<I", data, 80)[0]
    tris: List[Tri] = []
    offset = 84
    for _ in range(triangle_count):
        if offset + 50 > len(data):
            raise ValueError(f"{source}: binary STL truncated")
        a = struct.unpack_from("<3f", data, offset + 12)
        b = struct.unpack_from("<3f", data, offset + 24)
        c = struct.unpack_from("<3f", data, offset + 36)
        tris.append((a, b, c))
        offset += 50
    return tris


def read_binary_stl(path: Path) -> List[Tri]:
    return read_binary_stl_bytes(path.read_bytes(), str(path))


def read_ascii_stl_text(text: str, source: str = "ASCII STL") -> List[Tri]:
    tris: List[Tri] = []
    vertices: List[Vec3] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line.startswith("vertex "):
            continue
        parts = line.split()
        if len(parts) != 4:
            raise ValueError(f"{source}: malformed vertex line {raw_line!r}")
        vertex = (float(parts[1]), float(parts[2]), float(parts[3]))
        vertices.append(vertex)
        if len(vertices) == 3:
            tris.append((vertices[0], vertices[1], vertices[2]))
            vertices = []
    if vertices:
        raise ValueError(f"{source}: incomplete ASCII STL triangle")
    return tris


def read_ascii_stl(path: Path) -> List[Tri]:
    return read_ascii_stl_text(path.read_text(encoding="ascii"), str(path))


def read_letter_tile_stl(path: Path) -> List[Tri]:
    data = path.read_bytes()
    if data.lstrip().startswith(b"solid"):
        return read_ascii_stl_text(data.decode("ascii"), str(path))
    return read_binary_stl_bytes(data, str(path))


_LETTER_TILE_CACHE: Dict[str, List[Tri]] = {}


def letter_tile_path(letter: str) -> Path:
    return LETTER_TILES_DIR / f"{letter.upper()}.stl"


def load_letter_tile(letter: str) -> List[Tri]:
    key = letter.upper()
    cached = _LETTER_TILE_CACHE.get(key)
    if cached is not None:
        return cached
    path = letter_tile_path(key)
    if not path.is_file():
        raise ValueError(
            f"missing letter tile {path}; run vox2stl/build_letter_tiles.py to pre-render A-Z"
        )
    tris = read_letter_tile_stl(path)
    _LETTER_TILE_CACHE[key] = tris
    return tris


def place_letter_tris(
    template: Sequence[Tri],
    cx: float,
    cy: float,
    config: RenderConfig,
) -> List[Tri]:
    tile_span = 1.0 - 2.0 * DEFAULT_LABEL_RECESS_FRAC
    runtime_span = config.unit_mm - 2.0 * config.label_recess_mm
    xy_scale = runtime_span / tile_span if tile_span > 0.0 else config.unit_mm
    z_scale = (
        config.label_height_mm / DEFAULT_LABEL_HEIGHT_FRAC
        if DEFAULT_LABEL_HEIGHT_FRAC > 0.0
        else config.label_height_mm
    )

    def map_vertex(vertex: Vec3) -> Vec3:
        return (
            cx + vertex[0] * xy_scale,
            cy + vertex[1] * xy_scale,
            config.trace_z0_mm + vertex[2] * z_scale,
        )

    return [(map_vertex(a), map_vertex(b), map_vertex(c)) for a, b, c in template]


def letter_tris(cx: float, cy: float, char: str, config: RenderConfig) -> List[Tri]:
    if config.label_height_mm <= 0.0:
        return []
    template = load_letter_tile(char)
    return place_letter_tris(template, cx, cy, config)


def arm_box(cx: float, cy: float, direction: str, config: RenderConfig) -> BoxSolid:
    width = trace_width(config)
    half = width * 0.5
    max_hole_radius = max(config.pin_hole_diameter_mm, config.device_hole_diameter_mm) * 0.5
    reach = min(
        config.unit_mm * 0.5 + config.overlap_mm,
        config.unit_mm - max_hole_radius - config.trace_hole_clearance_mm,
    )
    if direction == "N":
        return BoxSolid(cx - half, cy - half, cx + half, cy + reach, config.trace_z0_mm, config.trace_z1_mm)
    if direction == "S":
        return BoxSolid(cx - half, cy - reach, cx + half, cy + half, config.trace_z0_mm, config.trace_z1_mm)
    if direction == "E":
        return BoxSolid(cx - half, cy - half, cx + reach, cy + half, config.trace_z0_mm, config.trace_z1_mm)
    if direction == "W":
        return BoxSolid(cx - reach, cy - half, cx + half, cy + half, config.trace_z0_mm, config.trace_z1_mm)
    raise ValueError(f"unknown arm direction {direction!r}")


def accepts_connection(char: str, direction: str) -> bool:
    if char in PAD_CHARS:
        return True
    return direction in ARMS_BY_CHAR.get(char, frozenset())


def connects_to_neighbor(char: str, neighbor: str, direction: str) -> bool:
    if char in PAD_CHARS and neighbor in PAD_CHARS:
        return False
    return accepts_connection(char, direction) and accepts_connection(
        neighbor, OPPOSITE_DIRECTION[direction]
    )


def neighbor_char(layer: Layer, row_index: int, col_index: int, direction: str) -> str:
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
    if next_row < 0 or next_row >= layer.height or next_col < 0 or next_col >= layer.width:
        return "."
    return layer_window(layer, layer.rows[next_row])[next_col]


def glyph_boxes(
    layer: Layer,
    row_index: int,
    col_index: int,
    char: str,
    cx: float,
    cy: float,
    config: RenderConfig,
) -> List[BoxSolid]:
    if char == PIN_PAD_CHAR and config.include_pads:
        return [square_box(cx, cy, pad_width(char, config), config.trace_z0_mm, config.trace_z1_mm)]
    if char == LEG_PAD_CHAR and config.include_pads:
        return [square_box(cx, cy, pad_width(char, config), config.trace_z0_mm, config.trace_z1_mm)]
    if is_label_char(char):
        return []

    arms = ARMS_BY_CHAR.get(char)
    if arms is None:
        return []

    boxes: List[BoxSolid] = [square_box(cx, cy, trace_width(config), config.trace_z0_mm, config.trace_z1_mm)]
    for direction in sorted(arms):
        neighbor = neighbor_char(layer, row_index, col_index, direction)
        if connects_to_neighbor(char, neighbor, direction):
            boxes.append(arm_box(cx, cy, direction, config))
    return boxes


def build_boxes(layer: Layer, config: RenderConfig) -> List[BoxSolid]:
    boxes: List[BoxSolid] = []
    for row_index, row in enumerate(layer.rows):
        window = layer_window(layer, row)
        for col_index, char in enumerate(window):
            cx, cy = cell_center(layer, row_index, col_index, config)
            boxes.extend(glyph_boxes(layer, row_index, col_index, char, cx, cy, config))
    return boxes


def build_holes(base_layer: Layer, config: RenderConfig) -> List[Hole]:
    holes: List[Hole] = []
    for row_index, row in enumerate(base_layer.rows):
        window = layer_window(base_layer, row)
        for col_index, char in enumerate(window):
            if char not in PAD_CHARS:
                continue
            cx, cy = cell_center(base_layer, row_index, col_index, config)
            diameter = config.pin_hole_diameter_mm if char == PIN_PAD_CHAR else config.device_hole_diameter_mm
            holes.append(Hole(cx, cy, diameter * 0.5))
    return holes


def box_contains_hole(box: BoxSolid, hole: Hole) -> bool:
    return (
        box.x0 - hole.radius <= hole.x <= box.x1 + hole.radius
        and box.y0 - hole.radius <= hole.y <= box.y1 + hole.radius
    )


def holes_for_box(box: BoxSolid, holes: Sequence[Hole]) -> List[Hole]:
    return [hole for hole in holes if box_contains_hole(box, hole)]


def mesh_from_boxes(boxes: Sequence[BoxSolid]) -> Mesh:
    mesh = Mesh()
    for box in boxes:
        mesh.extend(box_tris(box))
    return mesh


def build_layer_mesh(
    layer: Layer,
    config: RenderConfig,
    holes: Optional[Sequence[Hole]] = None,
) -> Tuple[Mesh, int, int]:
    mesh = Mesh()
    box_count = 0
    letter_count = 0
    for row_index, row in enumerate(layer.rows):
        window = layer_window(layer, row)
        for col_index, char in enumerate(window):
            cx, cy = cell_center(layer, row_index, col_index, config)
            if is_label_char(char):
                mesh.extend(letter_tris(cx, cy, char, config))
                letter_count += 1
                continue
            boxes = glyph_boxes(layer, row_index, col_index, char, cx, cy, config)
            box_count += len(boxes)
            for box in boxes:
                if holes is not None:
                    add_box_with_holes(mesh, box, holes, config.grid_mm)
                else:
                    mesh.extend(box_tris(box))
    return mesh, box_count, letter_count


def add_box_with_holes(mesh: Mesh, box: BoxSolid, holes: Sequence[Hole], grid_mm: float) -> None:
    box_holes = holes_for_box(box, holes)
    if box_holes:
        mesh.extend(plate_with_holes_tris(box, box_holes, grid_mm))
    else:
        mesh.extend(box_tris(box))


def full_mesh_from_layers(
    base_layer: Layer,
    trace_layer: Layer,
    config: RenderConfig,
) -> Tuple[Mesh, int, int, int]:
    mesh = Mesh()
    holes = build_holes(base_layer, config)
    base_box = layer_bounds(base_layer, config, config.base_z0_mm, config.base_z1_mm)
    mesh.extend(plate_with_holes_tris(base_box, holes, config.grid_mm))
    trace_mesh, box_count, letter_count = build_layer_mesh(trace_layer, config, holes)
    mesh.extend(trace_mesh.triangles)
    return mesh, len(holes), box_count, letter_count


def default_output_path(input_path: Path, layer_name: str) -> Path:
    return input_path.with_name(f"{input_path.stem}-{layer_name}.stl")


def solid_name_for(path: Path, layer_name: str) -> str:
    raw = f"{path.stem}_{layer_name}"
    return re.sub(r"[^A-Za-z0-9_]+", "_", raw)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vox_path", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--mode", choices=("layer", "full"), default="layer")
    parser.add_argument("--layer", default="trace")
    parser.add_argument("--base-layer", default="base")
    parser.add_argument("--solid-name")
    parser.add_argument("--unit-mm", type=float)
    parser.add_argument("--trace-width-mm", type=float, default=DEFAULT_TRACE_WIDTH_MM)
    parser.add_argument("--pad-width-mm", type=float, default=DEFAULT_PAD_WIDTH_MM)
    parser.add_argument("--device-pad-width-mm", type=float, default=DEFAULT_DEVICE_PAD_WIDTH_MM)
    parser.add_argument("--pin-hole-diameter-mm", type=float, default=DEFAULT_PIN_HOLE_DIAMETER_MM)
    parser.add_argument("--device-hole-diameter-mm", type=float, default=DEFAULT_DEVICE_HOLE_DIAMETER_MM)
    parser.add_argument("--adjacent-isolation-gap-mm", type=float, default=DEFAULT_ADJACENT_ISOLATION_GAP_MM)
    parser.add_argument("--overlap-mm", type=float, default=DEFAULT_OVERLAP_MM)
    parser.add_argument("--trace-hole-clearance-mm", type=float, default=DEFAULT_TRACE_HOLE_CLEARANCE_MM)
    parser.add_argument("--label-recess-mm", type=float, default=DEFAULT_LABEL_RECESS_MM)
    parser.add_argument("--label-height-mm", type=float, default=DEFAULT_LABEL_HEIGHT_MM)
    parser.add_argument("--base-z0-mm", type=float, default=DEFAULT_BASE_Z0_MM)
    parser.add_argument("--base-z1-mm", type=float, default=DEFAULT_BASE_Z1_MM)
    parser.add_argument("--trace-z0-mm", type=float)
    parser.add_argument("--trace-z1-mm", type=float, default=DEFAULT_TRACE_Z1_MM)
    parser.add_argument("--grid-mm", type=float, default=DEFAULT_GRID_MM)
    parser.add_argument("--origin-x-mm", type=float, default=0.0)
    parser.add_argument("--origin-y-mm", type=float, default=0.0)
    parser.add_argument("--no-pads", action="store_true")
    return parser.parse_args(argv)


def run(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    layers = read_layers(args.vox_path)
    file_unit = unit_from_file(args.vox_path)
    trace_z0_mm = args.trace_z0_mm if args.trace_z0_mm is not None else args.base_z1_mm
    config = RenderConfig(
        unit_mm=args.unit_mm if args.unit_mm is not None else file_unit or DEFAULT_UNIT_MM,
        trace_width_mm=args.trace_width_mm,
        pad_width_mm=args.pad_width_mm,
        device_pad_width_mm=args.device_pad_width_mm,
        pin_hole_diameter_mm=args.pin_hole_diameter_mm,
        device_hole_diameter_mm=args.device_hole_diameter_mm,
        adjacent_isolation_gap_mm=args.adjacent_isolation_gap_mm,
        overlap_mm=args.overlap_mm,
        trace_hole_clearance_mm=args.trace_hole_clearance_mm,
        label_recess_mm=args.label_recess_mm,
        label_height_mm=args.label_height_mm,
        base_z0_mm=args.base_z0_mm,
        base_z1_mm=args.base_z1_mm,
        trace_z0_mm=trace_z0_mm,
        trace_z1_mm=args.trace_z1_mm,
        grid_mm=args.grid_mm,
        origin_x_mm=args.origin_x_mm,
        origin_y_mm=args.origin_y_mm,
        include_pads=not args.no_pads,
    )

    names = ", ".join(sorted(layers))
    if args.mode == "full":
        base_layer = layers.get(args.base_layer)
        if base_layer is None:
            raise ValueError(f"{args.vox_path}: missing base layer {args.base_layer!r}; found {names}")
        trace_layer = layers.get(args.layer)
        if trace_layer is None:
            raise ValueError(f"{args.vox_path}: missing layer {args.layer!r}; found {names}")
        if (base_layer.width, base_layer.height) != (trace_layer.width, trace_layer.height):
            raise ValueError(
                f"{args.vox_path}: base and trace geometry differ: "
                f"{base_layer.width}x{base_layer.height} vs {trace_layer.width}x{trace_layer.height}"
            )
        mesh, hole_count, box_count, letter_count = full_mesh_from_layers(
            base_layer,
            trace_layer,
            config,
        )
        output_path = args.output or default_output_path(args.vox_path, "full")
        solid_name = args.solid_name or solid_name_for(args.vox_path, "full")
        layer_label = f"{args.base_layer}+{args.layer}"
    else:
        layer = layers.get(args.layer)
        if layer is None:
            raise ValueError(f"{args.vox_path}: missing layer {args.layer!r}; found {names}")
        mesh, box_count, letter_count = build_layer_mesh(layer, config)
        hole_count = 0
        output_path = args.output or default_output_path(args.vox_path, args.layer)
        solid_name = args.solid_name or solid_name_for(args.vox_path, args.layer)
        layer_label = args.layer

    mesh.write_ascii_stl(output_path, solid_name)
    print(f"Wrote {output_path}")
    print(f"Layer: {layer_label}")
    if args.mode == "full":
        print(f"Holes: {hole_count}")
    print(f"Boxes: {box_count}")
    if letter_count:
        print(f"Letters: {letter_count}")
    print(f"Triangles: {len(mesh.triangles)}")
    return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
