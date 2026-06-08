#!/usr/bin/env python3
"""Convert a text voxel layer to an ASCII STL feature mesh."""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

Vec3 = Tuple[float, float, float]
Tri = Tuple[Vec3, Vec3, Vec3]

DEFAULT_UNIT_MM = 2.54
DEFAULT_TRACE_WIDTH_FRAC = 0.72
DEFAULT_ADJACENT_ISOLATION_GAP_FRAC = 0.12
DEFAULT_PIN_HOLE_DIAMETER_FRAC = 1.10 / DEFAULT_UNIT_MM
DEFAULT_LEG_HOLE_DIAMETER_FRAC = DEFAULT_PIN_HOLE_DIAMETER_FRAC * 1.25
DEFAULT_PIN_OUTSIDE_FRAC = 0.88
DEFAULT_LEG_OUTSIDE_FRAC = 0.88
DEFAULT_TILE_OVERLAP_FRAC = 0.08
DEFAULT_TRACE_HOLE_CLEARANCE_FRAC = 0.04
DEFAULT_GRID_FRAC = 0.20
DEFAULT_TRACE_WIDTH_MM = DEFAULT_TRACE_WIDTH_FRAC * DEFAULT_UNIT_MM
DEFAULT_ADJACENT_ISOLATION_GAP_MM = DEFAULT_ADJACENT_ISOLATION_GAP_FRAC * DEFAULT_UNIT_MM
DEFAULT_PAD_WIDTH_MM = DEFAULT_PIN_OUTSIDE_FRAC * DEFAULT_UNIT_MM
DEFAULT_DEVICE_PAD_WIDTH_MM = DEFAULT_LEG_OUTSIDE_FRAC * DEFAULT_UNIT_MM
DEFAULT_PIN_HOLE_DIAMETER_MM = DEFAULT_PIN_HOLE_DIAMETER_FRAC * DEFAULT_UNIT_MM
DEFAULT_DEVICE_HOLE_DIAMETER_MM = DEFAULT_LEG_HOLE_DIAMETER_FRAC * DEFAULT_UNIT_MM
DEFAULT_OVERLAP_MM = DEFAULT_TILE_OVERLAP_FRAC * DEFAULT_UNIT_MM
DEFAULT_TRACE_HOLE_CLEARANCE_MM = DEFAULT_TRACE_HOLE_CLEARANCE_FRAC * DEFAULT_UNIT_MM
DEFAULT_BASE_Z0_MM = 0.0
DEFAULT_BASE_Z1_MM = 3.175
DEFAULT_TRACE_Z0_MM = DEFAULT_BASE_Z1_MM
DEFAULT_TRACE_Z1_MM = 6.350
DEFAULT_GRID_MM = DEFAULT_GRID_FRAC * DEFAULT_UNIT_MM

LAYER_HEADER_RE = re.compile(r"^layer\s+([A-Za-z0-9_-]+)\s+\((\d+),\s*(\d+),\s*(\d+)\)$")
UNIT_RE = re.compile(r"UNIT_MM\s*=\s*([0-9]+(?:\.[0-9]+)?)")

BOX_UL = "\u250c"
BOX_UR = "\u2510"
BOX_LL = "\u2514"
BOX_LR = "\u2518"
BOX_T_LEFT = "\u251c"
BOX_T_RIGHT = "\u2524"
BOX_T_DOWN = "\u252c"
BOX_T_UP = "\u2534"
BOX_CROSS = "\u253c"
BOX_H = "\u2500"
BOX_V = "\u2502"

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
OPPOSITE_DIRECTION: Dict[str, str] = {"N": "S", "E": "W", "S": "N", "W": "E"}


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
        current_rows.append(line)

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
    raw_width = config.pad_width_mm if char == "o" else config.device_pad_width_mm
    return isolated_width(raw_width, config)


def square_box(cx: float, cy: float, width: float, z0: float, z1: float) -> BoxSolid:
    half = width * 0.5
    return BoxSolid(cx - half, cy - half, cx + half, cy + half, z0, z1)


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
    if char in {"o", "O"}:
        return True
    return direction in ARMS_BY_CHAR.get(char, frozenset())


def connects_to_neighbor(char: str, neighbor: str, direction: str) -> bool:
    if char in {"o", "O"} and neighbor in {"o", "O"}:
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
    if char == "o" and config.include_pads:
        return [square_box(cx, cy, pad_width(char, config), config.trace_z0_mm, config.trace_z1_mm)]
    if char == "O" and config.include_pads:
        return [square_box(cx, cy, pad_width(char, config), config.trace_z0_mm, config.trace_z1_mm)]

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
            if char not in {"o", "O"}:
                continue
            cx, cy = cell_center(base_layer, row_index, col_index, config)
            diameter = config.pin_hole_diameter_mm if char == "o" else config.device_hole_diameter_mm
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


def add_box_with_holes(mesh: Mesh, box: BoxSolid, holes: Sequence[Hole], grid_mm: float) -> None:
    box_holes = holes_for_box(box, holes)
    if box_holes:
        mesh.extend(plate_with_holes_tris(box, box_holes, grid_mm))
    else:
        mesh.extend(box_tris(box))


def full_mesh_from_layers(base_layer: Layer, trace_layer: Layer, config: RenderConfig) -> Tuple[Mesh, int, int]:
    mesh = Mesh()
    holes = build_holes(base_layer, config)
    base_box = layer_bounds(base_layer, config, config.base_z0_mm, config.base_z1_mm)
    mesh.extend(plate_with_holes_tris(base_box, holes, config.grid_mm))
    trace_boxes = build_boxes(trace_layer, config)
    for box in trace_boxes:
        add_box_with_holes(mesh, box, holes, config.grid_mm)
    return mesh, len(holes), len(trace_boxes)


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
        mesh, hole_count, box_count = full_mesh_from_layers(base_layer, trace_layer, config)
        output_path = args.output or default_output_path(args.vox_path, "full")
        solid_name = args.solid_name or solid_name_for(args.vox_path, "full")
        layer_label = f"{args.base_layer}+{args.layer}"
    else:
        layer = layers.get(args.layer)
        if layer is None:
            raise ValueError(f"{args.vox_path}: missing layer {args.layer!r}; found {names}")
        boxes = build_boxes(layer, config)
        mesh = mesh_from_boxes(boxes)
        hole_count = 0
        box_count = len(boxes)
        output_path = args.output or default_output_path(args.vox_path, args.layer)
        solid_name = args.solid_name or solid_name_for(args.vox_path, args.layer)
        layer_label = args.layer

    mesh.write_ascii_stl(output_path, solid_name)
    print(f"Wrote {output_path}")
    print(f"Layer: {layer_label}")
    if args.mode == "full":
        print(f"Holes: {hole_count}")
    print(f"Boxes: {box_count}")
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
