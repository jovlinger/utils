#!/usr/bin/env python3
"""Build smooth solid letter meshes from thickened Hershey vector strokes."""

from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from hershey_simplex import Stroke, hershey_strokes

Vec2 = Tuple[float, float]
Vec3 = Tuple[float, float, float]
Tri = Tuple[Vec3, Vec3, Vec3]

DEFAULT_LABEL_RECESS_FRAC = 0.04
DEFAULT_LABEL_HEIGHT_FRAC = 0.40
DEFAULT_LABEL_TILE_MAX_TRIANGLES = 30000
DEFAULT_LABEL_RASTER_SIZE = 512
DEFAULT_LABEL_STROKE_FRAC = 0.20
DEFAULT_LABEL_BLUR_PASSES = 4
DEFAULT_LABEL_BLUR_RADIUS = 5
DEFAULT_MAX_VERTEX_VALENCE = 20


def distance_point_segment(px: float, py: float, ax: float, ay: float, bx: float, by: float) -> float:
    abx = bx - ax
    aby = by - ay
    apx = px - ax
    apy = py - ay
    denom = abx * abx + aby * aby
    if denom <= 1e-12:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, (apx * abx + apy * aby) / denom))
    cx = ax + t * abx
    cy = ay + t * aby
    return math.hypot(px - cx, py - cy)


def normalize_strokes(
    strokes: Sequence[Stroke],
    recess_frac: float,
    stroke_frac: float = 0.0,
) -> Tuple[Sequence[Stroke], float]:
    points: List[Vec2] = []
    for start, end in strokes:
        points.append((float(start[0]), float(start[1])))
        points.append((float(end[0]), float(end[1])))
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    width = max_x - min_x
    height = max_y - min_y
    span = max(width, height, 1.0)
    inset = 0.5 - recess_frac
    stroke_radius = stroke_frac * 0.5
    fit_inset = max(inset - stroke_radius, inset * 0.25)
    scale = (2.0 * fit_inset) / span
    center_x = (min_x + max_x) * 0.5
    center_y = (min_y + max_y) * 0.5
    normalized: List[Stroke] = []
    for start, end in strokes:
        sx = (float(start[0]) - center_x) * scale
        sy = (float(start[1]) - center_y) * scale
        ex = (float(end[0]) - center_x) * scale
        ey = (float(end[1]) - center_y) * scale
        normalized.append(((sx, sy), (ex, ey)))
    return normalized, scale


def rasterize_strokes(
    strokes: Sequence[Stroke],
    size: int,
    stroke_radius: float,
) -> List[float]:
    field = [0.0] * (size * size)
    if not strokes:
        return field
    margin = stroke_radius
    min_x = min(min(start[0], end[0]) for start, end in strokes) - margin
    max_x = max(max(start[0], end[0]) for start, end in strokes) + margin
    min_y = min(min(start[1], end[1]) for start, end in strokes) - margin
    max_y = max(max(start[1], end[1]) for start, end in strokes) + margin
    row_start = max(0, int(math.floor((min_y + 0.5) * size)))
    row_end = min(size - 1, int(math.ceil((max_y + 0.5) * size - 1.0)))
    col_start = max(0, int(math.floor((min_x + 0.5) * size)))
    col_end = min(size - 1, int(math.ceil((max_x + 0.5) * size - 1.0)))
    for row in range(row_start, row_end + 1):
        y = -0.5 + (row + 0.5) / size
        for col in range(col_start, col_end + 1):
            x = -0.5 + (col + 0.5) / size
            min_dist = float("inf")
            for start, end in strokes:
                dist = distance_point_segment(x, y, start[0], start[1], end[0], end[1])
                min_dist = min(min_dist, dist)
            if min_dist <= stroke_radius:
                field[row * size + col] = 1.0
    return field


def box_blur(field: Sequence[float], size: int, radius: int) -> List[float]:
    temp = [0.0] * (size * size)
    out = [0.0] * (size * size)
    diameter = radius * 2 + 1
    for row in range(size):
        acc = 0.0
        for col in range(size):
            left = max(0, col - radius)
            right = min(size - 1, col + radius)
            if col == 0:
                for index in range(left, right + 1):
                    acc += field[row * size + index]
            else:
                add_col = min(size - 1, col + radius)
                drop_col = max(0, col - radius - 1)
                acc += field[row * size + add_col] - field[row * size + drop_col]
            span = right - left + 1
            temp[row * size + col] = acc / span
    for col in range(size):
        acc = 0.0
        for row in range(size):
            top = max(0, row - radius)
            bottom = min(size - 1, row + radius)
            if row == 0:
                for index in range(top, bottom + 1):
                    acc += temp[index * size + col]
            else:
                add_row = min(size - 1, row + radius)
                drop_row = max(0, row - radius - 1)
                acc += temp[add_row * size + col] - temp[drop_row * size + col]
            span = bottom - top + 1
            out[row * size + col] = acc / span
    return out


def smooth_field(field: Sequence[float], size: int, passes: int, radius: int) -> List[float]:
    current = list(field)
    for _ in range(passes):
        current = box_blur(current, size, radius)
    return current


def marching_squares_contours(field: Sequence[float], size: int, iso: float) -> List[List[Vec2]]:
    # Bit order: 1=top-left, 2=top-right, 4=bottom-right, 8=bottom-left.
    # Edge indices: 0=top, 1=right, 2=bottom, 3=left.
    edge_table: Tuple[Tuple[int, ...], ...] = (
        (),
        (0, 3),
        (1, 0),
        (1, 3),
        (2, 1),
        (0, 3, 2, 1),
        (2, 0),
        (2, 3),
        (3, 2),
        (0, 2),
        (1, 0, 3, 2),
        (1, 2),
        (3, 1),
        (0, 1),
        (3, 0),
        (),
    )
    segments: List[Tuple[Vec2, Vec2]] = []

    def interp(ax: float, ay: float, av: float, bx: float, by: float, bv: float) -> Vec2:
        if abs(av - bv) < 1e-9:
            return (ax, ay)
        t = (iso - av) / (bv - av)
        return (ax + (bx - ax) * t, ay + (by - ay) * t)

    for row in range(size - 1):
        for col in range(size - 1):
            x0 = -0.5 + col / size
            x1 = -0.5 + (col + 1) / size
            y0 = -0.5 + row / size
            y1 = -0.5 + (row + 1) / size
            v0 = field[row * size + col]
            v1 = field[row * size + col + 1]
            v2 = field[(row + 1) * size + col + 1]
            v3 = field[(row + 1) * size + col]
            case = 0
            if v0 >= iso:
                case |= 1
            if v1 >= iso:
                case |= 2
            if v2 >= iso:
                case |= 4
            if v3 >= iso:
                case |= 8
            if case == 0 or case == 15:
                continue
            edge_points: List[Vec2 | None] = [None, None, None, None]
            edge_points[0] = interp(x0, y0, v0, x1, y0, v1)
            edge_points[1] = interp(x1, y0, v1, x1, y1, v2)
            edge_points[2] = interp(x0, y1, v3, x1, y1, v2)
            edge_points[3] = interp(x0, y0, v0, x0, y1, v3)
            edges = edge_table[case]
            if case in {5, 10}:
                center = (v0 + v1 + v2 + v3) * 0.25
                if case == 5:
                    edges = (0, 3, 2, 1) if center >= iso else (0, 1, 2, 3)
                else:
                    edges = (1, 0, 3, 2) if center >= iso else (1, 2, 3, 0)
            for index in range(0, len(edges), 2):
                start = edge_points[edges[index]]
                end = edge_points[edges[index + 1]]
                if start is not None and end is not None:
                    segments.append((start, end))

    point_map: dict[Tuple[int, int], Vec2] = {}
    adjacency: dict[Tuple[int, int], List[Tuple[int, int]]] = {}

    def key_for(point: Vec2) -> Tuple[int, int]:
        return (int(round(point[0] * 1_000_000.0)), int(round(point[1] * 1_000_000.0)))

    for start, end in segments:
        start_key = key_for(start)
        end_key = key_for(end)
        point_map[start_key] = start
        point_map[end_key] = end
        adjacency.setdefault(start_key, []).append(end_key)
        adjacency.setdefault(end_key, []).append(start_key)

    contours: List[List[Vec2]] = []
    visited_edges: set[Tuple[Tuple[int, int], Tuple[int, int]]] = set()
    for start_key, neighbors in adjacency.items():
        for neighbor_key in neighbors:
            edge = tuple(sorted((start_key, neighbor_key)))
            if edge in visited_edges:
                continue
            contour: List[Vec2] = [point_map[start_key]]
            prev_key = start_key
            current_key = neighbor_key
            visited_edges.add(edge)
            while current_key != start_key and len(contour) < len(adjacency) + 5:
                contour.append(point_map[current_key])
                next_candidates = [
                    candidate
                    for candidate in adjacency.get(current_key, [])
                    if candidate != prev_key
                ]
                if not next_candidates:
                    break
                next_key = next_candidates[0]
                edge = tuple(sorted((current_key, next_key)))
                if edge in visited_edges:
                    break
                visited_edges.add(edge)
                prev_key = current_key
                current_key = next_key
            if len(contour) >= 3:
                contours.append(contour)
    return contours


def polygon_area(points: Sequence[Vec2]) -> float:
    area = 0.0
    count = len(points)
    for index in range(count):
        x0, y0 = points[index]
        x1, y1 = points[(index + 1) % count]
        area += x0 * y1 - x1 * y0
    return area * 0.5


def simplify_polygon(points: Sequence[Vec2], epsilon: float) -> List[Vec2]:
    if len(points) < 3:
        return list(points)

    def perpendicular_distance(point: Vec2, start: Vec2, end: Vec2) -> float:
        if start == end:
            return math.hypot(point[0] - start[0], point[1] - start[1])
        num = abs(
            (end[1] - start[1]) * point[0]
            - (end[0] - start[0]) * point[1]
            + end[0] * start[1]
            - end[1] * start[0]
        )
        den = math.hypot(end[0] - start[0], end[1] - start[1])
        return num / den

    def rdp(segment: Sequence[Vec2]) -> List[Vec2]:
        if len(segment) < 3:
            return list(segment)
        start = segment[0]
        end = segment[-1]
        max_dist = -1.0
        index = 0
        for candidate_index in range(1, len(segment) - 1):
            dist = perpendicular_distance(segment[candidate_index], start, end)
            if dist > max_dist:
                max_dist = dist
                index = candidate_index
        if max_dist <= epsilon:
            return [start, end]
        left = rdp(segment[: index + 1])
        right = rdp(segment[index:])
        return left[:-1] + right

    closed = list(points)
    if closed[0] != closed[-1]:
        closed.append(closed[0])
    simplified = rdp(closed)
    if simplified and simplified[0] == simplified[-1]:
        simplified = simplified[:-1]
    return simplified


def triangulate_fan(points: Sequence[Vec2]) -> List[Tri]:
    if len(points) < 3:
        return []
    if polygon_area(points) < 0.0:
        ordered = list(reversed(points))
    else:
        ordered = list(points)
    anchor = ordered[0]
    tris: List[Tri] = []
    for index in range(1, len(ordered) - 1):
        a = (anchor[0], anchor[1], 0.0)
        b = (ordered[index][0], ordered[index][1], 0.0)
        c = (ordered[index + 1][0], ordered[index + 1][1], 0.0)
        tris.append((a, b, c))
    return tris


def extrude_polygon(points: Sequence[Vec2], z0: float, z1: float) -> List[Tri]:
    if len(points) < 3:
        return []
    top = [(point[0], point[1], z1) for point in points]
    bottom = [(point[0], point[1], z0) for point in points]
    tris: List[Tri] = []
    for index in range(1, len(points) - 1):
        tris.append((top[0], top[index], top[index + 1]))
        tris.append((bottom[0], bottom[index + 1], bottom[index]))
    count = len(points)
    for index in range(count):
        next_index = (index + 1) % count
        tris.append((bottom[index], bottom[next_index], top[next_index]))
        tris.append((bottom[index], top[next_index], top[index]))
    return tris


def mesh_from_contours(contours: Sequence[Sequence[Vec2]], height_frac: float) -> List[Tri]:
    tris: List[Tri] = []
    for contour in contours:
        if len(contour) < 3:
            continue
        tris.extend(extrude_polygon(contour, 0.0, height_frac))
    return tris


def mesh_resolution_frac(mesh_size: int) -> float:
    return 1.0 / float(mesh_size)


def max_triangle_edge_length(tris: Sequence[Tri]) -> float:
    longest = 0.0
    for a, b, c in tris:
        for p, q in ((a, b), (b, c), (c, a)):
            edge = math.hypot(p[0] - q[0], p[1] - q[1], p[2] - q[2])
            longest = max(longest, edge)
    return longest


def vertex_key(point: Vec3) -> Tuple[int, int, int]:
    scale = 1_000_000_000.0
    return (
        int(round(point[0] * scale)),
        int(round(point[1] * scale)),
        int(round(point[2] * scale)),
    )


def max_vertex_valence(tris: Sequence[Tri]) -> int:
    neighbors: dict[Tuple[int, int, int], set[Tuple[int, int, int]]] = {}
    for a, b, c in tris:
        for p, q in ((a, b), (b, c), (c, a)):
            kp = vertex_key(p)
            kq = vertex_key(q)
            if kp == kq:
                continue
            neighbors.setdefault(kp, set()).add(kq)
            neighbors.setdefault(kq, set()).add(kp)
    if not neighbors:
        return 0
    return max(len(adjacent) for adjacent in neighbors.values())


def assert_letter_mesh_edge_budget(
    tris: Sequence[Tri],
    *,
    height_frac: float,
    mesh_size: int,
    letter: str,
) -> None:
    if not tris:
        raise ValueError(f"letter {letter!r} produced no triangles")
    resolution = mesh_resolution_frac(mesh_size)
    limit = height_frac + resolution
    longest = max_triangle_edge_length(tris)
    if longest > limit + 1e-9:
        raise ValueError(
            f"letter {letter!r} max triangle edge {longest:.6f} exceeds "
            f"height_frac + mesh_resolution ({height_frac:.6f} + {resolution:.6f} = {limit:.6f})"
        )


def assert_letter_mesh_vertex_valence(
    tris: Sequence[Tri],
    *,
    letter: str,
    max_valence: int = DEFAULT_MAX_VERTEX_VALENCE,
) -> None:
    if not tris:
        raise ValueError(f"letter {letter!r} produced no triangles")
    valence = max_vertex_valence(tris)
    if valence > max_valence:
        raise ValueError(
            f"letter {letter!r} max vertex valence {valence} exceeds limit {max_valence}"
        )


def assert_letter_mesh_sanity(
    tris: Sequence[Tri],
    *,
    height_frac: float,
    mesh_size: int,
    letter: str,
    max_valence: int = DEFAULT_MAX_VERTEX_VALENCE,
) -> None:
    assert_letter_mesh_edge_budget(
        tris,
        height_frac=height_frac,
        mesh_size=mesh_size,
        letter=letter,
    )
    assert_letter_mesh_vertex_valence(
        tris,
        letter=letter,
        max_valence=max_valence,
    )


def box_tris(x0: float, y0: float, x1: float, y1: float, z0: float, z1: float) -> List[Tri]:
    corners = (
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    )
    faces = (
        (0, 2, 1),
        (0, 3, 2),
        (4, 5, 6),
        (4, 6, 7),
        (0, 1, 5),
        (0, 5, 4),
        (1, 2, 6),
        (1, 6, 5),
        (2, 3, 7),
        (2, 7, 6),
        (3, 0, 4),
        (3, 4, 7),
    )
    return tuple(
        (corners[i0], corners[i1], corners[i2])
        for i0, i1, i2 in faces
    )


def downsample_field(field: Sequence[float], raster_size: int, mesh_size: int) -> List[float]:
    if mesh_size == raster_size:
        return list(field)
    reduced: List[float] = []
    step = raster_size / mesh_size
    for row in range(mesh_size):
        src_row = min(raster_size - 1, int(row * step))
        for col in range(mesh_size):
            src_col = min(raster_size - 1, int(col * step))
            reduced.append(field[src_row * raster_size + src_col])
    return reduced


def subdivide_polygon_edges(points: Sequence[Vec2], max_segment: float) -> List[Vec2]:
    if len(points) < 2:
        return list(points)
    out: List[Vec2] = []
    count = len(points)
    for index in range(count):
        start = points[index]
        end = points[(index + 1) % count]
        out.append(start)
        length = math.hypot(end[0] - start[0], end[1] - start[1])
        if length <= max_segment:
            continue
        steps = int(math.ceil(length / max_segment))
        for step in range(1, steps):
            t = step / steps
            out.append(
                (
                    start[0] + t * (end[0] - start[0]),
                    start[1] + t * (end[1] - start[1]),
                )
            )
    return out


def extrude_contour_walls(contour: Sequence[Vec2], height_frac: float) -> List[Tri]:
    if len(contour) < 2:
        return []
    tris: List[Tri] = []
    count = len(contour)
    for index in range(count):
        x0, y0 = contour[index]
        x1, y1 = contour[(index + 1) % count]
        bottom_a = (x0, y0, 0.0)
        bottom_b = (x1, y1, 0.0)
        top_a = (x0, y0, height_frac)
        top_b = (x1, y1, height_frac)
        tris.append((bottom_a, bottom_b, top_b))
        tris.append((bottom_a, top_b, top_a))
    return tris


def field_cell_filled(
    field: Sequence[float],
    mesh_size: int,
    row: int,
    col: int,
    iso: float,
) -> bool:
    if row < 0 or col < 0 or row >= mesh_size or col >= mesh_size:
        return False
    return field[row * mesh_size + col] >= iso


def mesh_from_filled_field(
    field: Sequence[float],
    mesh_size: int,
    height_frac: float,
    iso: float = 0.5,
) -> List[Tri]:
    cell = mesh_resolution_frac(mesh_size)
    tris: List[Tri] = []
    for row in range(mesh_size):
        y0 = -0.5 + row / mesh_size
        y1 = y0 + cell
        for col in range(mesh_size):
            if not field_cell_filled(field, mesh_size, row, col, iso):
                continue
            x0 = -0.5 + col / mesh_size
            x1 = x0 + cell
            z1 = height_frac
            top = (
                (x0, y0, z1),
                (x1, y0, z1),
                (x1, y1, z1),
                (x0, y1, z1),
            )
            tris.append((top[0], top[1], top[2]))
            tris.append((top[0], top[2], top[3]))
    for contour in marching_squares_contours(field, mesh_size, iso):
        subdivided = subdivide_polygon_edges(contour, cell)
        tris.extend(extrude_contour_walls(subdivided, height_frac))
    return tris


def generate_letter_tile_triangles(
    letter: str,
    *,
    recess_frac: float = DEFAULT_LABEL_RECESS_FRAC,
    height_frac: float = DEFAULT_LABEL_HEIGHT_FRAC,
    max_triangles: int = DEFAULT_LABEL_TILE_MAX_TRIANGLES,
    raster_size: int = DEFAULT_LABEL_RASTER_SIZE,
    stroke_frac: float = DEFAULT_LABEL_STROKE_FRAC,
    blur_passes: int = DEFAULT_LABEL_BLUR_PASSES,
    blur_radius: int = DEFAULT_LABEL_BLUR_RADIUS,
) -> List[Tri]:
    _, strokes = hershey_strokes(letter)
    normalized, _ = normalize_strokes(strokes, recess_frac, stroke_frac)
    stroke_radius = stroke_frac * 0.5
    field = rasterize_strokes(normalized, raster_size, stroke_radius)
    field = smooth_field(field, raster_size, blur_passes, blur_radius)

    mesh_sizes = [192, 160, 128, 112, 96, 80, 64]
    last_error: ValueError | None = None
    for mesh_size in mesh_sizes:
        work_field = downsample_field(field, raster_size, mesh_size)
        tris = mesh_from_filled_field(work_field, mesh_size, height_frac)
        if not tris or len(tris) > max_triangles:
            continue
        try:
            assert_letter_mesh_sanity(
                tris,
                height_frac=height_frac,
                mesh_size=mesh_size,
                letter=letter,
            )
        except ValueError as exc:
            last_error = exc
            continue
        return tris
    if last_error is not None:
        raise last_error
    raise ValueError(f"letter {letter!r} could not be meshed within triangle budget {max_triangles}")
