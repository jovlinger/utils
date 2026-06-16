#!/usr/bin/env python3
"""Convert a text voxel layer to an ASCII STL feature mesh."""

from __future__ import annotations

import argparse
import gzip
import math
import pickle
import re
import struct
import sys
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple, Union

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
    DEFAULT_COND_LIG_FRAC,
    DEFAULT_COND_LIG_MM,
    DEFAULT_DEVICE_HOLE_DIAMETER_MM,
    DEFAULT_DEVICE_PAD_WIDTH_MM,
    DEFAULT_GRID_MM,
    DEFAULT_GRID_FRAC,
    DEFAULT_ISOL_LIG_FRAC,
    DEFAULT_ISOL_LIG_MM,
    DEFAULT_LABEL_BLUR_PASSES,
    DEFAULT_LABEL_BLUR_RADIUS,
    DEFAULT_LABEL_HEIGHT_FRAC,
    DEFAULT_LABEL_HEIGHT_MM,
    DEFAULT_LETTER_STYLE,
    DEFAULT_LABEL_RASTER_SIZE,
    DEFAULT_LABEL_RECESS_FRAC,
    DEFAULT_LABEL_RECESS_MM,
    DEFAULT_LABEL_STROKE_FRAC,
    DEFAULT_LABEL_TILE_MAX_TRIANGLES,
    DEFAULT_LAYER_THICKNESS_MM,
    DEFAULT_LEG_OUTSIDE_FRAC,
    DEFAULT_MAX_VERTEX_VALENCE,
    DEFAULT_OVERLAP_MM,
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
    LEG_PAD_CHAR,
    LETTER_TILES_DIR,
    OPPOSITE_DIRECTION,
    PAD_CHARS,
    PIN_PAD_CHAR,
    SHORTHAND_DIRECT_CHARS,
    TILE_CACHE_PATH,
    parse_alias_line,
    parse_layer_header,
    UNIT_RE,
)
from letter_mesh import generate_letter_tile_triangles

Vec3 = Tuple[float, float, float]
Tri = Tuple[Vec3, Vec3, Vec3]
LigatureKey = Tuple[str, int, int, int, int]
TileCacheKey = Union[str, LigatureKey]
TileCache = Dict[TileCacheKey, List[Tri]]
LetterFootprintBox = Tuple[float, float, float, float]


@dataclass(frozen=True)
class Layer:
    name: str
    offset: int
    width: int
    height: int
    rows: Tuple[str, ...]
    layer_thickness_mm: float = DEFAULT_LAYER_THICKNESS_MM
    letter_style: str = DEFAULT_LETTER_STYLE


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
class CylindricalVoid:
    x: float
    y: float
    radius: float
    z0: float
    z1: float


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
    cond_lig_mm: float = DEFAULT_COND_LIG_MM
    isol_lig_mm: float = DEFAULT_ISOL_LIG_MM
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
    voids = [CylindricalVoid(hole.x, hole.y, hole.radius, box.z0, box.z1) for hole in holes]
    return mesh_from_boxes_and_voids([box], [], voids, grid_mm).triangles


def read_layers(path: Path) -> Dict[str, Layer]:
    layers: Dict[str, Layer] = {}
    aliases: Dict[str, str] = {}
    current_name: Optional[str] = None
    current_offset = 0
    current_width = 0
    current_height = 0
    current_layer_thickness_mm = DEFAULT_LAYER_THICKNESS_MM
    current_letter_style = DEFAULT_LETTER_STYLE
    current_rows: List[str] = []

    def finish_layer() -> None:
        nonlocal current_name, current_offset, current_width, current_height, current_layer_thickness_mm, current_letter_style, current_rows
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
            layer_thickness_mm=current_layer_thickness_mm,
            letter_style=current_letter_style,
        )
        current_name = None
        current_rows = []

    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.rstrip("\n")
        stripped_line = line.strip()
        if not stripped_line or stripped_line.startswith("#"):
            continue
        alias = parse_alias_line(line.strip())
        if alias is not None:
            aliases[alias.source] = alias.target
            continue
        header = parse_layer_header(line)
        if header is not None:
            finish_layer()
            current_name = header.name
            if current_name in layers:
                raise ValueError(f"{path}:{line_no}: duplicate layer {current_name!r}")
            current_offset = header.offset
            current_width = header.width
            current_height = header.height
            current_layer_thickness_mm = header.layer_thickness_mm
            current_letter_style = header.letter_style
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


def hole_radius_for_pad(char: str, config: RenderConfig) -> float:
    diameter = config.pin_hole_diameter_mm if char == PIN_PAD_CHAR else config.device_hole_diameter_mm
    return diameter * 0.5


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
_LETTER_FOOTPRINT_CACHE: Dict[str, List[LetterFootprintBox]] = {}


def letter_tile_path(letter: str) -> Path:
    return LETTER_TILES_DIR / f"{letter.upper()}.stl"


def load_letter_tile(letter: str) -> List[Tri]:
    key = letter.upper()
    cached = _LETTER_TILE_CACHE.get(key)
    if cached is not None:
        return cached
    path = letter_tile_path(key)
    if path.is_file():
        tris = read_letter_tile_stl(path)
    else:
        tris = generate_letter_tile_triangles(key)
    _LETTER_TILE_CACHE[key] = tris
    return tris


def letter_xy_scale(config: RenderConfig) -> float:
    tile_span = 1.0 - 2.0 * DEFAULT_LABEL_RECESS_FRAC
    runtime_span = config.unit_mm - 2.0 * config.label_recess_mm
    return runtime_span / tile_span if tile_span > 0.0 else config.unit_mm


def letter_tile_footprint_boxes(letter: str) -> List[LetterFootprintBox]:
    key = letter.upper()
    cached = _LETTER_FOOTPRINT_CACHE.get(key)
    if cached is not None:
        return cached
    boxes: Dict[Tuple[int, int, int, int], LetterFootprintBox] = {}
    for triangle in load_letter_tile(key):
        if any(abs(vertex[2] - DEFAULT_LABEL_HEIGHT_FRAC) > 1e-6 for vertex in triangle):
            continue
        xs = [vertex[0] for vertex in triangle]
        ys = [vertex[1] for vertex in triangle]
        x0 = min(xs)
        x1 = max(xs)
        y0 = min(ys)
        y1 = max(ys)
        if x1 <= x0 or y1 <= y0:
            continue
        rounded_key = (
            int(round(x0 * 1_000_000_000.0)),
            int(round(y0 * 1_000_000_000.0)),
            int(round(x1 * 1_000_000_000.0)),
            int(round(y1 * 1_000_000_000.0)),
        )
        boxes[rounded_key] = (x0, y0, x1, y1)
    cached = list(boxes.values())
    _LETTER_FOOTPRINT_CACHE[key] = cached
    return cached


def letter_footprint_voids(
    char: str,
    config: RenderConfig,
    *,
    z0: float,
    z1: float,
    mirror_x: bool,
) -> List[BoxSolid]:
    if config.label_height_mm <= 0.0 or z1 <= z0:
        return []
    xy_scale = letter_xy_scale(config)
    voids: List[BoxSolid] = []
    for x0, y0, x1, y1 in letter_tile_footprint_boxes(char):
        if mirror_x:
            x0, x1 = -x1, -x0
        voids.append(
            BoxSolid(
                x0 * xy_scale,
                y0 * xy_scale,
                x1 * xy_scale,
                y1 * xy_scale,
                z0,
                z1,
            )
        )
    return voids


def place_letter_tris(
    template: Sequence[Tri],
    cx: float,
    cy: float,
    config: RenderConfig,
) -> List[Tri]:
    xy_scale = letter_xy_scale(config)
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


_PERSISTENT_TILE_CACHE: Optional[TileCache] = None
_RUNTIME_TILE_CACHES: Dict[Tuple[float, ...], TileCache] = {}
TILE_CACHE_SIGNATURE_KEY = "__tile_cache_signature__"


def tile_cache_signature(config: RenderConfig) -> Tuple[float, ...]:
    return (
        round(config.unit_mm, 9),
        round(config.trace_width_mm, 9),
        round(config.pad_width_mm, 9),
        round(config.device_pad_width_mm, 9),
        round(config.pin_hole_diameter_mm, 9),
        round(config.device_hole_diameter_mm, 9),
        round(config.trace_z0_mm, 9),
        round(config.trace_z1_mm, 9),
        round(config.grid_mm, 9),
        round(config.cond_lig_mm, 9),
        round(config.isol_lig_mm, 9),
        round(config.label_recess_mm, 9),
        round(config.label_height_mm, 9),
        float(config.include_pads),
    )


def persistent_tile_cache_enabled(config: RenderConfig) -> bool:
    default = RenderConfig()
    return tile_cache_signature(config) == tile_cache_signature(default)


def load_persistent_tile_cache() -> TileCache:
    global _PERSISTENT_TILE_CACHE
    if _PERSISTENT_TILE_CACHE is not None:
        return _PERSISTENT_TILE_CACHE
    if TILE_CACHE_PATH.is_file():
        with gzip.open(TILE_CACHE_PATH, "rb") as file_obj:
            loaded = pickle.load(file_obj)
        if not isinstance(loaded, dict):
            raise ValueError(f"{TILE_CACHE_PATH}: tile cache is not a dictionary")
        _PERSISTENT_TILE_CACHE = loaded
    else:
        _PERSISTENT_TILE_CACHE = {}
    return _PERSISTENT_TILE_CACHE


def save_persistent_tile_cache(cache: TileCache) -> None:
    TILE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(TILE_CACHE_PATH, "wb") as file_obj:
        pickle.dump(cache, file_obj, protocol=pickle.HIGHEST_PROTOCOL)


def format_tile_cache_key(key: TileCacheKey) -> str:
    if isinstance(key, str):
        return repr(key)
    return repr(key)


def report_tile_cache_miss(key: TileCacheKey) -> None:
    print(f"Rendering tile cache key {format_tile_cache_key(key)}", file=sys.stderr)


def tile_cache_for_config(config: RenderConfig) -> Tuple[TileCache, bool]:
    if persistent_tile_cache_enabled(config):
        cache = load_persistent_tile_cache()
        signature = tile_cache_signature(config)
        if cache.get(TILE_CACHE_SIGNATURE_KEY) != signature:
            cache.clear()
            cache[TILE_CACHE_SIGNATURE_KEY] = signature
        seed_pre_rendered_letters(cache, config)
        return cache, True
    signature = tile_cache_signature(config)
    return _RUNTIME_TILE_CACHES.setdefault(signature, {}), False


def seed_pre_rendered_letters(cache: TileCache, config: RenderConfig) -> None:
    dirty = False
    for letter in "abcdefghijklmnopqrstuvwxyz":
        if letter in cache:
            continue
        report_tile_cache_miss(letter)
        template = load_letter_tile(letter)
        cache[letter] = place_letter_tris(template, 0.0, 0.0, config)
        dirty = True
    if dirty:
        save_persistent_tile_cache(cache)


def translate_tris(tris: Sequence[Tri], dx: float, dy: float) -> List[Tri]:
    def translate_vertex(vertex: Vec3) -> Vec3:
        return (vertex[0] + dx, vertex[1] + dy, vertex[2])

    return [(translate_vertex(a), translate_vertex(b), translate_vertex(c)) for a, b, c in tris]


def cached_tile_tris(key: TileCacheKey, config: RenderConfig) -> List[Tri]:
    cache, persistent = tile_cache_for_config(config)
    cached = cache.get(key)
    if cached is not None:
        return cached
    if isinstance(key, str):
        report_tile_cache_miss(key)
        tris = render_naive_tile(key, config)
    else:
        cached_tile_tris(key[0], config)
        report_tile_cache_miss(key)
        tris = render_ligature_tile(key, config)
    cache[key] = tris
    if persistent:
        save_persistent_tile_cache(cache)
    return tris


def local_ligature_box(direction: str, length: float, width: float, config: RenderConfig) -> BoxSolid:
    half_width = width * 0.5
    half_length = length * 0.5
    edge = config.unit_mm * 0.5
    if direction == "N":
        return BoxSolid(
            -half_width,
            edge - half_length,
            half_width,
            edge + half_length,
            config.trace_z0_mm,
            config.trace_z1_mm,
        )
    if direction == "S":
        return BoxSolid(
            -half_width,
            -edge - half_length,
            half_width,
            -edge + half_length,
            config.trace_z0_mm,
            config.trace_z1_mm,
        )
    if direction == "E":
        return BoxSolid(
            edge - half_length,
            -half_width,
            edge + half_length,
            half_width,
            config.trace_z0_mm,
            config.trace_z1_mm,
        )
    if direction == "W":
        return BoxSolid(
            -edge - half_length,
            -half_width,
            -edge + half_length,
            half_width,
            config.trace_z0_mm,
            config.trace_z1_mm,
        )
    raise ValueError(f"unknown ligature direction {direction!r}")


def isolation_ligature_width(config: RenderConfig) -> float:
    return max(pad_width(PIN_PAD_CHAR, config), pad_width(LEG_PAD_CHAR, config))


def render_naive_tile(char: str, config: RenderConfig) -> List[Tri]:
    if is_label_char(char):
        template = load_letter_tile(char)
        return place_letter_tris(template, 0.0, 0.0, config)
    if char in PAD_CHARS:
        if not config.include_pads:
            return []
        boxes = [square_box(0.0, 0.0, pad_width(char, config), config.trace_z0_mm, config.trace_z1_mm)]
        voids = [CylindricalVoid(0.0, 0.0, hole_radius_for_pad(char, config), config.trace_z0_mm, config.trace_z1_mm)]
        return mesh_from_boxes_and_voids(boxes, [], voids, config.grid_mm).triangles
    if char in ARMS_BY_CHAR:
        boxes = [square_box(0.0, 0.0, trace_width(config), config.trace_z0_mm, config.trace_z1_mm)]
        return mesh_from_boxes_and_voids(boxes, [], [], config.grid_mm).triangles
    return []


def render_ligature_tile(key: LigatureKey, config: RenderConfig) -> List[Tri]:
    char, north, east, south, west = key
    if char in PAD_CHARS:
        if not config.include_pads:
            return []
        additive_boxes = [square_box(0.0, 0.0, pad_width(char, config), config.trace_z0_mm, config.trace_z1_mm)]
    elif char in ARMS_BY_CHAR:
        additive_boxes = [square_box(0.0, 0.0, trace_width(config), config.trace_z0_mm, config.trace_z1_mm)]
    else:
        return []

    rect_voids: List[BoxSolid] = []
    direction_states = (("N", north), ("E", east), ("S", south), ("W", west))
    for direction, state in direction_states:
        if state == 1:
            additive_boxes.append(
                local_ligature_box(direction, config.cond_lig_mm, trace_width(config), config)
            )
        elif state == -1:
            rect_voids.append(
                local_ligature_box(
                    direction,
                    config.isol_lig_mm,
                    isolation_ligature_width(config),
                    config,
                )
            )
    cylinder_voids: List[CylindricalVoid] = []
    if char in PAD_CHARS:
        cylinder_voids.append(
            CylindricalVoid(0.0, 0.0, hole_radius_for_pad(char, config), config.trace_z0_mm, config.trace_z1_mm)
        )
    return mesh_from_boxes_and_voids(additive_boxes, rect_voids, cylinder_voids, config.grid_mm).triangles


def arm_reach(config: RenderConfig, neighbor: str = ".") -> float:
    if neighbor in PAD_CHARS:
        return min(
            config.unit_mm - pad_width(neighbor, config) * 0.5 + config.overlap_mm,
            config.unit_mm - hole_radius_for_pad(neighbor, config) - config.trace_hole_clearance_mm,
        )
    max_hole_radius = max(config.pin_hole_diameter_mm, config.device_hole_diameter_mm) * 0.5
    return min(
        config.unit_mm * 0.5 + config.overlap_mm,
        config.unit_mm - max_hole_radius - config.trace_hole_clearance_mm,
    )


def directional_box(
    cx: float,
    cy: float,
    direction: str,
    width: float,
    reach: float,
    config: RenderConfig,
) -> BoxSolid:
    half = width * 0.5
    if direction == "N":
        return BoxSolid(cx - half, cy - half, cx + half, cy + reach, config.trace_z0_mm, config.trace_z1_mm)
    if direction == "S":
        return BoxSolid(cx - half, cy - reach, cx + half, cy + half, config.trace_z0_mm, config.trace_z1_mm)
    if direction == "E":
        return BoxSolid(cx - half, cy - half, cx + reach, cy + half, config.trace_z0_mm, config.trace_z1_mm)
    if direction == "W":
        return BoxSolid(cx - reach, cy - half, cx + half, cy + half, config.trace_z0_mm, config.trace_z1_mm)
    raise ValueError(f"unknown arm direction {direction!r}")


def arm_box(cx: float, cy: float, direction: str, config: RenderConfig, neighbor: str = ".") -> BoxSolid:
    width = trace_width(config)
    return directional_box(cx, cy, direction, width, arm_reach(config, neighbor), config)


def pad_tail_box(cx: float, cy: float, direction: str, config: RenderConfig) -> BoxSolid:
    return directional_box(
        cx,
        cy,
        direction,
        trace_width(config),
        config.unit_mm * 0.5 + config.overlap_mm,
        config,
    )


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
    if char in PAD_CHARS and config.include_pads:
        boxes = [square_box(cx, cy, pad_width(char, config), config.trace_z0_mm, config.trace_z1_mm)]
        for direction in sorted(ARMS_BY_CHAR[BOX_CROSS]):
            neighbor = neighbor_char(layer, row_index, col_index, direction)
            if connects_to_neighbor(char, neighbor, direction):
                boxes.append(pad_tail_box(cx, cy, direction, config))
        return boxes
    if is_label_char(char):
        return []

    arms = ARMS_BY_CHAR.get(char)
    if arms is None:
        return []

    boxes: List[BoxSolid] = [square_box(cx, cy, trace_width(config), config.trace_z0_mm, config.trace_z1_mm)]
    for direction in sorted(arms):
        neighbor = neighbor_char(layer, row_index, col_index, direction)
        if connects_to_neighbor(char, neighbor, direction):
            boxes.append(arm_box(cx, cy, direction, config, neighbor))
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
            holes.append(Hole(cx, cy, hole_radius_for_pad(char, config)))
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


def add_stepped_coords(coords: List[float], start: float, end: float, grid_mm: float) -> None:
    coords.append(start)
    coords.append(end)
    if end <= start:
        return
    steps = max(1, int(math.ceil((end - start) / grid_mm)))
    for index in range(1, steps):
        coords.append(start + (end - start) * index / steps)


def sorted_unique_coords(coords: Iterable[float]) -> List[float]:
    values = sorted(coords)
    unique: List[float] = []
    for value in values:
        if not unique or abs(value - unique[-1]) > 1e-9:
            unique.append(value)
    return unique


def grid_coords_for_solids(
    boxes: Sequence[BoxSolid],
    rect_voids: Sequence[BoxSolid],
    cylinder_voids: Sequence[CylindricalVoid],
    grid_mm: float,
) -> Tuple[List[float], List[float]]:
    if grid_mm <= 0.0:
        raise ValueError("grid-mm must be positive")
    min_x = min(box.x0 for box in boxes)
    max_x = max(box.x1 for box in boxes)
    min_y = min(box.y0 for box in boxes)
    max_y = max(box.y1 for box in boxes)
    x_coords: List[float] = []
    y_coords: List[float] = []
    add_stepped_coords(x_coords, min_x, max_x, grid_mm)
    add_stepped_coords(y_coords, min_y, max_y, grid_mm)
    for box in list(boxes) + list(rect_voids):
        x_coords.extend([box.x0, box.x1])
        y_coords.extend([box.y0, box.y1])
    for void in cylinder_voids:
        x_coords.extend([void.x - void.radius, void.x, void.x + void.radius])
        y_coords.extend([void.y - void.radius, void.y, void.y + void.radius])
    return sorted_unique_coords(x_coords), sorted_unique_coords(y_coords)


def z_levels_for_solids(
    boxes: Sequence[BoxSolid],
    rect_voids: Sequence[BoxSolid],
    cylinder_voids: Sequence[CylindricalVoid],
) -> List[float]:
    levels: List[float] = []
    for box in list(boxes) + list(rect_voids):
        levels.extend([box.z0, box.z1])
    for void in cylinder_voids:
        levels.extend([void.z0, void.z1])
    return sorted_unique_coords(levels)


def box_contains_point(box: BoxSolid, x: float, y: float, z: float) -> bool:
    return box.x0 <= x <= box.x1 and box.y0 <= y <= box.y1 and box.z0 <= z <= box.z1


def cylinder_void_contains_point(void: CylindricalVoid, x: float, y: float, z: float) -> bool:
    if z < void.z0 or z > void.z1:
        return False
    dx = x - void.x
    dy = y - void.y
    return dx * dx + dy * dy <= void.radius * void.radius


def point_is_solid(
    x: float,
    y: float,
    z: float,
    boxes: Sequence[BoxSolid],
    rect_voids: Sequence[BoxSolid],
    cylinder_voids: Sequence[CylindricalVoid],
) -> bool:
    if not any(box_contains_point(box, x, y, z) for box in boxes):
        return False
    if any(box_contains_point(void, x, y, z) for void in rect_voids):
        return False
    return not any(cylinder_void_contains_point(void, x, y, z) for void in cylinder_voids)


def append_quad(mesh: Mesh, a: Vec3, b: Vec3, c: Vec3, d: Vec3) -> None:
    mesh.extend([(a, b, c), (a, c, d)])


def append_cell_faces(
    mesh: Mesh,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    z0: float,
    z1: float,
    west: bool,
    east: bool,
    south: bool,
    north: bool,
    bottom: bool,
    top: bool,
) -> None:
    if bottom:
        append_quad(mesh, (x0, y0, z0), (x0, y1, z0), (x1, y1, z0), (x1, y0, z0))
    if top:
        append_quad(mesh, (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1))
    if west:
        append_quad(mesh, (x0, y0, z0), (x0, y0, z1), (x0, y1, z1), (x0, y1, z0))
    if east:
        append_quad(mesh, (x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1))
    if south:
        append_quad(mesh, (x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1))
    if north:
        append_quad(mesh, (x0, y1, z0), (x0, y1, z1), (x1, y1, z1), (x1, y1, z0))


def mesh_from_boxes_and_voids(
    boxes: Sequence[BoxSolid],
    rect_voids: Sequence[BoxSolid],
    cylinder_voids: Sequence[CylindricalVoid],
    grid_mm: float,
) -> Mesh:
    mesh = Mesh()
    if not boxes:
        return mesh
    x_coords, y_coords = grid_coords_for_solids(boxes, rect_voids, cylinder_voids, grid_mm)
    z_levels = z_levels_for_solids(boxes, rect_voids, cylinder_voids)
    slab_cells: List[List[List[bool]]] = []
    slab_ranges: List[Tuple[float, float]] = []
    for z0, z1 in zip(z_levels, z_levels[1:]):
        if z1 <= z0:
            continue
        z_mid = (z0 + z1) * 0.5
        rows: List[List[bool]] = []
        for y0, y1 in zip(y_coords, y_coords[1:]):
            y_mid = (y0 + y1) * 0.5
            row: List[bool] = []
            for x0, x1 in zip(x_coords, x_coords[1:]):
                x_mid = (x0 + x1) * 0.5
                row.append(point_is_solid(x_mid, y_mid, z_mid, boxes, rect_voids, cylinder_voids))
            rows.append(row)
        slab_cells.append(rows)
        slab_ranges.append((z0, z1))

    for slab_index, rows in enumerate(slab_cells):
        z0, z1 = slab_ranges[slab_index]
        previous_rows = slab_cells[slab_index - 1] if slab_index > 0 else None
        next_rows = slab_cells[slab_index + 1] if slab_index + 1 < len(slab_cells) else None
        for y_index, row in enumerate(rows):
            for x_index, occupied in enumerate(row):
                if not occupied:
                    continue
                west = x_index == 0 or not row[x_index - 1]
                east = x_index + 1 == len(row) or not row[x_index + 1]
                south = y_index == 0 or not rows[y_index - 1][x_index]
                north = y_index + 1 == len(rows) or not rows[y_index + 1][x_index]
                bottom = previous_rows is None or not previous_rows[y_index][x_index]
                top = next_rows is None or not next_rows[y_index][x_index]
                append_cell_faces(
                    mesh,
                    x_coords[x_index],
                    y_coords[y_index],
                    x_coords[x_index + 1],
                    y_coords[y_index + 1],
                    z0,
                    z1,
                    west,
                    east,
                    south,
                    north,
                    bottom,
                    top,
                )
    return mesh


def collect_layer_additives(layer: Layer, config: RenderConfig) -> Tuple[List[BoxSolid], Mesh, int, int]:
    boxes: List[BoxSolid] = []
    letters = Mesh()
    letter_count = 0
    for row_index, row in enumerate(layer.rows):
        window = layer_window(layer, row)
        for col_index, char in enumerate(window):
            cx, cy = cell_center(layer, row_index, col_index, config)
            if is_label_char(char):
                if layer.letter_style == "positive":
                    letters.extend(letter_tris(cx, cy, char, config))
                    letter_count += 1
                continue
            boxes.extend(glyph_boxes(layer, row_index, col_index, char, cx, cy, config))
    return boxes, letters, len(boxes), letter_count


def has_rendered_copper(char: str, config: RenderConfig) -> bool:
    if char in PAD_CHARS:
        return config.include_pads
    return char in ARMS_BY_CHAR


def direction_state_for_cell(
    layer: Layer,
    row_index: int,
    col_index: int,
    char: str,
    direction: str,
    config: RenderConfig,
) -> int:
    neighbor = neighbor_char(layer, row_index, col_index, direction)
    if connects_to_neighbor(char, neighbor, direction):
        return 1
    if has_rendered_copper(neighbor, config):
        return -1
    return 0


def ligature_key_for_cell(
    layer: Layer,
    row_index: int,
    col_index: int,
    char: str,
    config: RenderConfig,
) -> LigatureKey:
    return (
        char,
        direction_state_for_cell(layer, row_index, col_index, char, "N", config),
        direction_state_for_cell(layer, row_index, col_index, char, "E", config),
        direction_state_for_cell(layer, row_index, col_index, char, "S", config),
        direction_state_for_cell(layer, row_index, col_index, char, "W", config),
    )


def render_base_tile(
    char: str,
    config: RenderConfig,
    *,
    letter_style: str = DEFAULT_LETTER_STYLE,
) -> List[Tri]:
    if char == ".":
        return []
    box = BoxSolid(
        -config.unit_mm * 0.5,
        -config.unit_mm * 0.5,
        config.unit_mm * 0.5,
        config.unit_mm * 0.5,
        config.base_z0_mm,
        config.base_z1_mm,
    )
    rect_voids: List[BoxSolid] = []
    cylinder_voids: List[CylindricalVoid] = []
    if char in PAD_CHARS:
        cylinder_voids.append(
            CylindricalVoid(0.0, 0.0, hole_radius_for_pad(char, config), config.base_z0_mm, config.base_z1_mm)
        )
    if is_label_char(char) and letter_style == "negative":
        recess_z0 = max(config.base_z0_mm, config.base_z1_mm - config.label_height_mm)
        rect_voids.extend(
            letter_footprint_voids(
                char,
                config,
                z0=recess_z0,
                z1=config.base_z1_mm,
                mirror_x=True,
            )
        )
    return mesh_from_boxes_and_voids([box], rect_voids, cylinder_voids, config.grid_mm).triangles


def build_base_mesh(base_layer: Layer, config: RenderConfig) -> Tuple[Mesh, int]:
    mesh = Mesh()
    hole_count = 0
    base_tile_cache: Dict[str, List[Tri]] = {}
    for row_index, row in enumerate(base_layer.rows):
        window = layer_window(base_layer, row)
        for col_index, char in enumerate(window):
            if char == ".":
                continue
            if char in PAD_CHARS:
                hole_count += 1
            local_tris = base_tile_cache.get(char)
            if local_tris is None:
                local_tris = render_base_tile(char, config, letter_style=base_layer.letter_style)
                base_tile_cache[char] = local_tris
            cx, cy = cell_center(base_layer, row_index, col_index, config)
            mesh.extend(translate_tris(local_tris, cx, cy))
    return mesh, hole_count


def build_ligature_layer_mesh(layer: Layer, config: RenderConfig) -> Tuple[Mesh, int, int]:
    mesh = Mesh()
    tile_count = 0
    letter_count = 0
    for row_index, row in enumerate(layer.rows):
        window = layer_window(layer, row)
        for col_index, char in enumerate(window):
            if is_label_char(char):
                if layer.letter_style != "positive":
                    continue
                key: TileCacheKey = char
                letter_count += 1
            elif has_rendered_copper(char, config):
                key = ligature_key_for_cell(layer, row_index, col_index, char, config)
                tile_count += 1
            else:
                continue
            cx, cy = cell_center(layer, row_index, col_index, config)
            mesh.extend(translate_tris(cached_tile_tris(key, config), cx, cy))
    return mesh, tile_count, letter_count


def trace_air_gap_voids(layer: Layer, config: RenderConfig) -> List[BoxSolid]:
    voids: List[BoxSolid] = []
    half_gap = config.adjacent_isolation_gap_mm * 0.5
    for row_index, row in enumerate(layer.rows):
        window = layer_window(layer, row)
        for col_index, char in enumerate(window):
            if not has_rendered_copper(char, config):
                continue
            cx, cy = cell_center(layer, row_index, col_index, config)
            for direction in ("E", "S"):
                neighbor = neighbor_char(layer, row_index, col_index, direction)
                if not has_rendered_copper(neighbor, config) or connects_to_neighbor(char, neighbor, direction):
                    continue
                if direction == "E":
                    boundary_x = cx + config.unit_mm * 0.5
                    voids.append(
                        BoxSolid(
                            boundary_x - half_gap,
                            cy - config.unit_mm * 0.5,
                            boundary_x + half_gap,
                            cy + config.unit_mm * 0.5,
                            config.trace_z0_mm,
                            config.trace_z1_mm,
                        )
                    )
                else:
                    boundary_y = cy - config.unit_mm * 0.5
                    voids.append(
                        BoxSolid(
                            cx - config.unit_mm * 0.5,
                            boundary_y - half_gap,
                            cx + config.unit_mm * 0.5,
                            boundary_y + half_gap,
                            config.trace_z0_mm,
                            config.trace_z1_mm,
                        )
                    )
    return voids


def cylindrical_voids_for_holes(holes: Sequence[Hole], z0: float, z1: float, radius_extra: float = 0.0) -> List[CylindricalVoid]:
    return [
        CylindricalVoid(hole.x, hole.y, hole.radius + radius_extra, z0, z1)
        for hole in holes
        if hole.radius + radius_extra > 0.0 and z1 > z0
    ]


def build_layer_mesh(
    layer: Layer,
    config: RenderConfig,
    holes: Optional[Sequence[Hole]] = None,
) -> Tuple[Mesh, int, int]:
    if holes is None:
        return build_ligature_layer_mesh(layer, config)
    boxes, letters, box_count, letter_count = collect_layer_additives(layer, config)
    voids = cylindrical_voids_for_holes(
        holes,
        config.trace_z0_mm,
        config.trace_z1_mm,
        config.trace_hole_clearance_mm,
    )
    mesh = mesh_from_boxes_and_voids(boxes, [], voids, config.grid_mm)
    mesh.extend(letters.triangles)
    return mesh, box_count, letter_count


def add_box_with_holes(mesh: Mesh, box: BoxSolid, holes: Sequence[Hole], grid_mm: float) -> None:
    box_holes = holes_for_box(box, holes)
    if box_holes:
        mesh.extend(plate_with_holes_tris(box, box_holes, grid_mm))
    else:
        mesh.extend(box_tris(box))


def config_with_base_z(config: RenderConfig, z0_mm: float, z1_mm: float) -> RenderConfig:
    return replace(config, base_z0_mm=z0_mm, base_z1_mm=z1_mm)


def config_with_trace_z(config: RenderConfig, z0_mm: float, z1_mm: float) -> RenderConfig:
    return replace(config, trace_z0_mm=z0_mm, trace_z1_mm=z1_mm)


def full_mesh_from_layers(
    base_layer: Layer,
    trace_layer: Layer,
    config: RenderConfig,
) -> Tuple[Mesh, int, int, int]:
    base_z0_mm = config.base_z0_mm
    base_z1_mm = base_z0_mm + base_layer.layer_thickness_mm
    trace_z0_mm = base_z1_mm
    trace_z1_mm = trace_z0_mm + trace_layer.layer_thickness_mm
    base_config = config_with_base_z(config, base_z0_mm, base_z1_mm)
    trace_config = config_with_trace_z(config, trace_z0_mm, trace_z1_mm)

    mesh, hole_count = build_base_mesh(base_layer, base_config)
    trace_mesh, tile_count, letter_count = build_ligature_layer_mesh(trace_layer, trace_config)
    mesh.extend(trace_mesh.triangles)
    return mesh, hole_count, tile_count, letter_count


def default_output_path(input_path: Path, layer_name: str) -> Path:
    return input_path.with_name(f"{input_path.stem}-{layer_name}.stl")


def solid_name_for(path: Path, layer_name: str) -> str:
    raw = f"{path.stem}_{layer_name}"
    return re.sub(r"[^A-Za-z0-9_]+", "_", raw)


def add_cli_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("vox_path", type=Path)
    parser.add_argument("-o", "--output", type=Path)
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
    parser.add_argument("--cond-lig-mm", type=float, default=DEFAULT_COND_LIG_MM)
    parser.add_argument("--isol-lig-mm", type=float, default=DEFAULT_ISOL_LIG_MM)
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


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    add_cli_arguments(parser)
    return parser.parse_args(argv)


def run_from_args(args: argparse.Namespace) -> int:
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
        cond_lig_mm=args.cond_lig_mm,
        isol_lig_mm=args.isol_lig_mm,
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

    mesh.write_ascii_stl(output_path, solid_name)
    print(f"Wrote {output_path}")
    print(f"Layers: {layer_label}")
    print(f"Holes: {hole_count}")
    print(f"Boxes: {box_count}")
    if letter_count:
        print(f"Letters: {letter_count}")
    print(f"Triangles: {len(mesh.triangles)}")
    return 0


def run(argv: Sequence[str]) -> int:
    return run_from_args(parse_args(argv))


def main(argv: Optional[Sequence[str]] = None) -> int:
    try:
        return run(sys.argv[1:] if argv is None else argv)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
