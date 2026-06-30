#!/usr/bin/env python3
"""Generate thermo Pico2W sensor HAT STL (v1) for copper-tape 3D PCB printing.

Mechanical pin layout from Raspberry Pi Pico KiCad footprint
(RaspberryPi_Pico_Common_THT_MountingHoles, ki-lime-pi-pico), matching the
51 mm x 21 mm Pico / Pico 2 W DIP header grid (2.54 mm pitch, 1 mm drills).

Signal pins follow thermo/onboard/hardware/pico2w PLAN.md and config.rs:
  AHT20: GP4 (SDA), GP5 (SCL) on I2C0
  IR TX: GP14, IR RX: GP15
  Power: 3V3 and GND rails between header rows

Output: thermo-pico2w-sensor-hat-v1.stl (millimeters, Z-up, Bambu A1 Mini).
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

Vec3 = Tuple[float, float, float]
Tri = Tuple[Vec3, Vec3, Vec3]

# 1/8 inch board with two raised feature levels for copper-tape routing.
INCH_MM = 25.4
BASE_THICKNESS_MM = INCH_MM / 8.0
UNCONNECTED_RAISE_MM = 1.25
TRACE_RAISE_MM = INCH_MM / 8.0
PIN_HOLE_DIAMETER_MM = 1.1
MOUNT_HOLE_DIAMETER_MM = 2.4
SENSOR_HOLE_DIAMETER_MM = 2.1
GRID_MM = 0.5
TRACE_WIDTH_MM = 1.35
RAIL_WIDTH_MM = 1.775
PICO_PAD_WIDTH_MM = 1.7
SENSOR_PAD_WIDTH_MM = 2.35
MOUNT_PAD_WIDTH_MM = 3.4
BOARD_MARGIN_MM = 2.0
USB_CUT_WIDTH_MM = 9.0
USB_CUT_NORTH_Y_MM = -24.8

# Pico through-hole pads (KiCad footprint, board center at origin)
PICO_PADS_MM: dict[int, Tuple[float, float]] = {
    1: (-8.89, -24.13),
    2: (-8.89, -21.59),
    3: (-8.89, -19.05),
    4: (-8.89, -16.51),
    5: (-8.89, -13.97),
    6: (-8.89, -11.43),
    7: (-8.89, -8.89),
    8: (-8.89, -6.35),
    9: (-8.89, -3.81),
    10: (-8.89, -1.27),
    11: (-8.89, 1.27),
    12: (-8.89, 3.81),
    13: (-8.89, 6.35),
    14: (-8.89, 8.89),
    15: (-8.89, 11.43),
    16: (-8.89, 13.97),
    17: (-8.89, 16.51),
    18: (-8.89, 19.05),
    19: (-8.89, 21.59),
    20: (-8.89, 24.13),
    21: (8.89, 24.13),
    22: (8.89, 21.59),
    23: (8.89, 19.05),
    24: (8.89, 16.51),
    25: (8.89, 13.97),
    26: (8.89, 11.43),
    27: (8.89, 8.89),
    28: (8.89, 6.35),
    29: (8.89, 3.81),
    30: (8.89, 1.27),
    31: (8.89, -1.27),
    32: (8.89, -3.81),
    33: (8.89, -6.35),
    34: (8.89, -8.89),
    35: (8.89, -11.43),
    36: (8.89, -13.97),
    37: (8.89, -16.51),
    38: (8.89, -19.05),
    39: (8.89, -21.59),
    40: (8.89, -24.13),
}

PICO_MOUNT_HOLES_MM: Tuple[Tuple[float, float], ...] = (
    (-5.7, -23.5),
    (-5.7, 23.5),
    (5.7, -23.5),
    (5.7, 23.5),
)

# Used nets for v1 (physical pin numbers on Pico header)
PIN_GP4 = 6
PIN_GP5 = 7
PIN_GP14 = 19
PIN_GP15 = 20
PIN_3V3_A = 36
PIN_GND_A = 3
PIN_GND_B = 8
PIN_GND_C = 38

PITCH_MM = 2.54


@dataclass(frozen=True)
class Hole:
    x: float
    y: float
    radius: float


@dataclass(frozen=True)
class RectCut:
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class BoxSolid:
    x0: float
    y0: float
    x1: float
    y1: float
    z0: float
    z1: float
    label: str | None = None


@dataclass(frozen=True)
class Variant:
    name: str
    trace_text_lines: Tuple[str, ...]
    legacy_alias: bool = False


VARIANTS: Tuple[Variant, ...] = (
    Variant("up-side", ("UP", "SIDE"), True),
    Variant("pico-side", ("PICO", "SIDE"), False),
)


class Mesh:
    def __init__(self) -> None:
        self.triangles: List[Tri] = []

    def extend(self, tris: Iterable[Tri]) -> None:
        self.triangles.extend(tris)

    def write_ascii_stl(self, path: Path, name: str) -> None:
        lines: List[str] = [f"solid {name}"]
        for a, b, c in self.triangles:
            normal = _normal(a, b, c)
            lines.append(
                f"  facet normal {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}"
            )
            lines.append("    outer loop")
            for v in (a, b, c):
                lines.append(f"      vertex {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}")
            lines.append("    endloop")
            lines.append("  endfacet")
        lines.append(f"endsolid {name}")
        path.write_text("\n".join(lines) + "\n", encoding="ascii")


def _normal(a: Vec3, b: Vec3, c: Vec3) -> Vec3:
    ux, uy, uz = b[0] - a[0], b[1] - a[1], b[2] - a[2]
    vx, vy, vz = c[0] - a[0], c[1] - a[1], c[2] - a[2]
    nx = uy * vz - uz * vy
    ny = uz * vx - ux * vz
    nz = ux * vy - uy * vx
    length = math.sqrt(nx * nx + ny * ny + nz * nz)
    if length == 0.0:
        return (0.0, 0.0, 1.0)
    return (nx / length, ny / length, nz / length)


def box_tris(
    x0: float, y0: float, x1: float, y1: float, z0: float, z1: float
) -> List[Tri]:
    pts = [
        (x0, y0, z0),
        (x1, y0, z0),
        (x1, y1, z0),
        (x0, y1, z0),
        (x0, y0, z1),
        (x1, y0, z1),
        (x1, y1, z1),
        (x0, y1, z1),
    ]
    faces = [
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
    for i in range(segments):
        a0 = 2.0 * math.pi * i / segments
        a1 = 2.0 * math.pi * (i + 1) / segments
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


def _inside_hole(
    x: float, y: float, holes: Sequence[Hole], rects: Sequence[RectCut]
) -> bool:
    for hole in holes:
        dx = x - hole.x
        dy = y - hole.y
        if dx * dx + dy * dy <= hole.radius * hole.radius:
            return True
    for rect in rects:
        if rect.x0 <= x <= rect.x1 and rect.y0 <= y <= rect.y1:
            return True
    return False


def plate_with_holes_tris(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    z0: float,
    z1: float,
    holes: Sequence[Hole],
    rects: Sequence[RectCut] = (),
    grid: float = GRID_MM,
) -> List[Tri]:
    tris: List[Tri] = []
    x = x0
    while x < x1 - 1e-6:
        xn = min(x + grid, x1)
        y = y0
        while y < y1 - 1e-6:
            yn = min(y + grid, y1)
            cx = (x + xn) * 0.5
            cy = (y + yn) * 0.5
            if not _inside_hole(cx, cy, holes, rects):
                tris.extend(
                    [
                        ((x, y, z0), (xn, y, z0), (xn, yn, z0)),
                        ((x, y, z0), (xn, yn, z0), (x, yn, z0)),
                        ((x, y, z1), (xn, yn, z1), (xn, y, z1)),
                        ((x, y, z1), (x, yn, z1), (xn, yn, z1)),
                    ]
                )
            y = yn
        x = xn

    for hole in holes:
        tris.extend(cylinder_wall_tris(hole.x, hole.y, hole.radius, z0, z1))

    # Outer vertical walls (four sides), skipping cells that intersect holes near edge.
    def edge_strip(
        fixed_coord: float,
        var_start: float,
        var_end: float,
        axis: str,
        outward: str,
    ) -> None:
        var = var_start
        while var < var_end - 1e-6:
            vnext = min(var + grid, var_end)
            mid = (var + vnext) * 0.5
            if axis == "x":
                cx, cy = fixed_coord, mid
            else:
                cx, cy = mid, fixed_coord
            if _inside_hole(cx, cy, holes, rects):
                var = vnext
                continue
            if axis == "x":
                if outward == "neg":
                    tris.extend(
                        [
                            (
                                (fixed_coord, var, z0),
                                (fixed_coord, vnext, z0),
                                (fixed_coord, vnext, z1),
                            ),
                            (
                                (fixed_coord, var, z0),
                                (fixed_coord, vnext, z1),
                                (fixed_coord, var, z1),
                            ),
                        ]
                    )
                else:
                    tris.extend(
                        [
                            (
                                (fixed_coord, var, z1),
                                (fixed_coord, vnext, z1),
                                (fixed_coord, vnext, z0),
                            ),
                            (
                                (fixed_coord, var, z1),
                                (fixed_coord, vnext, z0),
                                (fixed_coord, var, z0),
                            ),
                        ]
                    )
            else:
                if outward == "neg":
                    tris.extend(
                        [
                            (
                                (var, fixed_coord, z0),
                                (vnext, fixed_coord, z0),
                                (vnext, fixed_coord, z1),
                            ),
                            (
                                (var, fixed_coord, z0),
                                (vnext, fixed_coord, z1),
                                (var, fixed_coord, z1),
                            ),
                        ]
                    )
                else:
                    tris.extend(
                        [
                            (
                                (var, fixed_coord, z1),
                                (vnext, fixed_coord, z1),
                                (vnext, fixed_coord, z0),
                            ),
                            (
                                (var, fixed_coord, z1),
                                (vnext, fixed_coord, z0),
                                (var, fixed_coord, z0),
                            ),
                        ]
                    )
            var = vnext

    edge_strip(x0, y0, y1, "x", "neg")
    edge_strip(x1, y0, y1, "x", "pos")
    edge_strip(y0, x0, x1, "y", "neg")
    edge_strip(y1, x0, x1, "y", "pos")
    return tris


def trace_boxes_from_path(
    points: Sequence[Tuple[float, float]],
    width: float,
    z0: float,
    z1: float,
    label: str | None = None,
) -> List[BoxSolid]:
    boxes: List[BoxSolid] = []
    half = width * 0.5
    for (xa, ya), (xb, yb) in zip(points, points[1:]):
        if abs(xa - xb) < 1e-6:
            y_lo, y_hi = (ya, yb) if ya <= yb else (yb, ya)
            boxes.append(
                BoxSolid(xa - half, y_lo - half, xa + half, y_hi + half, z0, z1, label)
            )
        else:
            x_lo, x_hi = (xa, xb) if xa <= xb else (xb, xa)
            boxes.append(
                BoxSolid(x_lo - half, ya - half, x_hi + half, ya + half, z0, z1, label)
            )
    return boxes


def pad_box(
    center: Tuple[float, float], width: float, z0: float, z1: float, label: str | None
) -> BoxSolid:
    half = width * 0.5
    x, y = center
    return BoxSolid(x - half, y - half, x + half, y + half, z0, z1, label)


TEXT_FONT: dict[str, Tuple[str, ...]] = {
    "B": ("110", "101", "110", "101", "110"),
    "C": ("111", "100", "100", "100", "111"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "I": ("111", "010", "010", "010", "111"),
    "O": ("111", "101", "101", "101", "111"),
    "P": ("110", "101", "110", "100", "100"),
    "S": ("111", "100", "111", "001", "111"),
    "U": ("101", "101", "101", "101", "111"),
}


def text_boxes(
    text: str,
    center: Tuple[float, float],
    cell: float,
    z0: float,
    z1: float,
) -> List[BoxSolid]:
    text = text.upper()
    char_width = 3
    char_gap = 1
    total_cols = 0
    for char in text:
        total_cols += char_width if char != " " else char_width
        total_cols += char_gap
    total_cols = max(total_cols - char_gap, 0)
    total_width = total_cols * cell
    total_height = 5 * cell
    x_start = center[0] - total_width * 0.5
    y_top = center[1] + total_height * 0.5
    boxes: List[BoxSolid] = []
    col_offset = 0

    for char in text:
        rows = TEXT_FONT.get(char)
        if rows is not None:
            for row_idx, row in enumerate(rows):
                for col_idx, bit in enumerate(row):
                    if bit != "1":
                        continue
                    x0 = x_start + (col_offset + col_idx) * cell
                    y1 = y_top - row_idx * cell
                    boxes.append(BoxSolid(x0, y1 - cell, x0 + cell, y1, z0, z1, None))
        col_offset += char_width + char_gap

    return boxes


def multiline_text_boxes(
    lines: Sequence[str],
    center: Tuple[float, float],
    cell: float,
    line_gap: float,
    z0: float,
    z1: float,
) -> List[BoxSolid]:
    line_height = 5 * cell
    total_height = len(lines) * line_height + max(len(lines) - 1, 0) * line_gap
    y_top = center[1] + total_height * 0.5
    boxes: List[BoxSolid] = []

    for index, line in enumerate(lines):
        line_center_y = y_top - line_height * 0.5 - index * (line_height + line_gap)
        boxes.extend(text_boxes(line, (center[0], line_center_y), cell, z0, z1))

    return boxes


def all_holes(sensor_sites: Sequence[Tuple[float, float]]) -> List[Hole]:
    holes: List[Hole] = []
    pin_r = PIN_HOLE_DIAMETER_MM * 0.5
    for _pin, (x, y) in PICO_PADS_MM.items():
        holes.append(Hole(x, y, pin_r))
    mount_r = MOUNT_HOLE_DIAMETER_MM * 0.5
    for x, y in PICO_MOUNT_HOLES_MM:
        holes.append(Hole(x, y, mount_r))
    sensor_r = SENSOR_HOLE_DIAMETER_MM * 0.5
    for x, y in sensor_sites:
        holes.append(Hole(x, y, sensor_r))
    return holes


def sensor_module_holes(
    variant: Variant,
) -> Tuple[List[Tuple[float, float]], dict[str, Tuple[float, float]]]:
    """Return all sensor pad centers and named signal pad targets."""
    # Module rows stay between the Pico header rows. Both variants use this
    # trace-side order; flat-side modules must be oriented to match it.
    aht_y = -11.43
    aht_x0 = -6.35
    aht: List[Tuple[float, float]] = [(aht_x0 + i * PITCH_MM, aht_y) for i in range(4)]
    irtx_y = 8.89
    irrx_y = 16.51
    pads = {
        "aht_sda": aht[0],
        "aht_scl": aht[1],
        "aht_gnd": aht[2],
        "aht_vcc": aht[3],
        "irtx_dat": (-3.81, irtx_y),
        "irtx_gnd": (-1.27, irtx_y),
        "irtx_vcc": (1.27, irtx_y),
        "irrx_out": (-3.81, irrx_y),
        "irrx_gnd": (-1.27, irrx_y),
        "irrx_vcc": (1.27, irrx_y),
    }
    sites: List[Tuple[float, float]] = list(aht)
    for key in ("irtx_vcc", "irtx_dat", "irtx_gnd", "irrx_vcc", "irrx_out", "irrx_gnd"):
        sites.append(pads[key])
    return sites, pads


def intended_trace_points(
    pads: dict[str, Tuple[float, float]],
) -> List[Tuple[float, float]]:
    points: List[Tuple[float, float]] = [
        PICO_PADS_MM[PIN_GP4],
        PICO_PADS_MM[PIN_GP5],
        PICO_PADS_MM[PIN_GP14],
        PICO_PADS_MM[PIN_GP15],
        PICO_PADS_MM[PIN_3V3_A],
        PICO_PADS_MM[PIN_GND_A],
        PICO_PADS_MM[PIN_GND_B],
        PICO_PADS_MM[PIN_GND_C],
    ]
    points.extend(pads.values())
    return points


def build_unconnected_boxes(pads: dict[str, Tuple[float, float]]) -> List[BoxSolid]:
    z0 = BASE_THICKNESS_MM
    z1 = BASE_THICKNESS_MM + UNCONNECTED_RAISE_MM
    connected = set(intended_trace_points(pads))
    boxes: List[BoxSolid] = []

    for _pin, center in PICO_PADS_MM.items():
        if center not in connected:
            boxes.append(pad_box(center, PICO_PAD_WIDTH_MM, z0, z1, None))

    for center in PICO_MOUNT_HOLES_MM:
        boxes.append(pad_box(center, MOUNT_PAD_WIDTH_MM, z0, z1, None))

    return boxes


def build_trace_boxes(
    variant: Variant, pads: dict[str, Tuple[float, float]]
) -> List[BoxSolid]:
    z0 = BASE_THICKNESS_MM
    z1 = BASE_THICKNESS_MM + TRACE_RAISE_MM

    def pt(pin: int) -> Tuple[float, float]:
        return PICO_PADS_MM[pin]

    rail_gnd_x = -1.27
    rail_3v3_x = 1.27
    rail_y0 = -19.05
    rail_y1 = 18.0
    rail_half = RAIL_WIDTH_MM * 0.5
    rails: List[BoxSolid] = [
        BoxSolid(
            rail_gnd_x - rail_half,
            rail_y0,
            rail_gnd_x + rail_half,
            rail_y1,
            z0,
            z1,
            "GND",
        ),
        BoxSolid(
            rail_3v3_x - rail_half,
            -13.97,
            rail_3v3_x + rail_half,
            rail_y1,
            z0,
            z1,
            "3V3",
        ),
    ]

    def trace(points: Sequence[Tuple[float, float]], label: str) -> List[BoxSolid]:
        return trace_boxes_from_path(points, TRACE_WIDTH_MM, z0, z1, label)

    def pico_pad(center: Tuple[float, float], label: str) -> BoxSolid:
        return pad_box(center, PICO_PAD_WIDTH_MM, z0, z1, label)

    def module_pad(center: Tuple[float, float], label: str) -> BoxSolid:
        return pad_box(center, SENSOR_PAD_WIDTH_MM, z0, z1, label)

    boxes: List[BoxSolid] = []
    boxes.extend(rails)

    for pin, label in (
        (PIN_GP4, "GP4"),
        (PIN_GP5, "GP5"),
        (PIN_GP14, "GP14"),
        (PIN_GP15, "GP15"),
        (PIN_3V3_A, "3V3"),
        (PIN_GND_A, "GND"),
        (PIN_GND_B, "GND"),
        (PIN_GND_C, "GND"),
    ):
        boxes.append(pico_pad(pt(pin), label))

    for key, label in (
        ("aht_vcc", "3V3"),
        ("aht_sda", "GP4"),
        ("aht_scl", "GP5"),
        ("aht_gnd", "GND"),
        ("irtx_vcc", "3V3"),
        ("irtx_dat", "GP14"),
        ("irtx_gnd", "GND"),
        ("irrx_vcc", "3V3"),
        ("irrx_out", "GP15"),
        ("irrx_gnd", "GND"),
    ):
        boxes.append(module_pad(pads[key], label))

    boxes.extend(trace([pt(PIN_3V3_A), (rail_3v3_x, pt(PIN_3V3_A)[1])], "3V3"))
    boxes.extend(trace([pt(PIN_GND_A), (rail_gnd_x, pt(PIN_GND_A)[1])], "GND"))
    boxes.extend(trace([pt(PIN_GND_B), (rail_gnd_x, pt(PIN_GND_B)[1])], "GND"))
    boxes.extend(trace([pt(PIN_GND_C), (rail_gnd_x, pt(PIN_GND_C)[1])], "GND"))

    boxes.extend(trace([pt(PIN_GP4), pads["aht_sda"]], "GP4"))
    boxes.extend(
        trace(
            [
                pt(PIN_GP5),
                (-3.81, pt(PIN_GP5)[1]),
                pads["aht_scl"],
            ],
            "GP5",
        )
    )
    boxes.extend(
        trace(
            [
                pt(PIN_GP14),
                (-7.11, pt(PIN_GP14)[1]),
                (-7.11, pads["irtx_dat"][1]),
                pads["irtx_dat"],
            ],
            "GP14",
        )
    )
    boxes.extend(
        trace(
            [
                pt(PIN_GP15),
                (-5.08, pt(PIN_GP15)[1]),
                (-5.08, pads["irrx_out"][1]),
                pads["irrx_out"],
            ],
            "GP15",
        )
    )

    return boxes


def holes_for_box(box: BoxSolid, holes: Sequence[Hole]) -> List[Hole]:
    touching: List[Hole] = []
    for hole in holes:
        if (
            box.x0 - hole.radius <= hole.x <= box.x1 + hole.radius
            and box.y0 - hole.radius <= hole.y <= box.y1 + hole.radius
        ):
            touching.append(hole)
    return touching


def boxes_overlap(a: BoxSolid, b: BoxSolid) -> bool:
    return min(a.x1, b.x1) > max(a.x0, b.x0) and min(a.y1, b.y1) > max(a.y0, b.y0)


def validate_trace_boxes(boxes: Sequence[BoxSolid]) -> None:
    problems: List[str] = []
    for i, a in enumerate(boxes):
        for b in boxes[i + 1 :]:
            if a.label is None or b.label is None or a.label == b.label:
                continue
            if boxes_overlap(a, b):
                problems.append(f"{a.label} overlaps {b.label}")
    if problems:
        raise ValueError("High-layer net overlap: " + "; ".join(problems[:5]))


def board_bounds(holes: Sequence[Hole]) -> Tuple[float, float, float, float]:
    x0 = min(hole.x - hole.radius for hole in holes) - BOARD_MARGIN_MM
    y0 = min(hole.y - hole.radius for hole in holes) - BOARD_MARGIN_MM
    x1 = max(hole.x + hole.radius for hole in holes) + BOARD_MARGIN_MM
    y1 = max(hole.y + hole.radius for hole in holes) + BOARD_MARGIN_MM
    return x0, y0, x1, y1


def build_emboss_boxes(variant: Variant) -> List[BoxSolid]:
    z0 = BASE_THICKNESS_MM
    text_z1 = BASE_THICKNESS_MM + UNCONNECTED_RAISE_MM
    trace_z1 = BASE_THICKNESS_MM + TRACE_RAISE_MM
    boxes: List[BoxSolid] = []
    boxes.extend(text_boxes("USB", (0.0, -23.45), 0.34, z0, text_z1))
    boxes.extend(
        multiline_text_boxes(
            variant.trace_text_lines, (0.0, 23.50), 0.34, 0.34, z0, text_z1
        )
    )
    boxes.extend(
        trace_boxes_from_path(
            [(5.20, 19.05), (7.20, 19.05)], TRACE_WIDTH_MM, z0, trace_z1
        )
    )
    return boxes


def build_mesh(variant: Variant) -> Mesh:
    mesh = Mesh()
    sensor_sites, pads = sensor_module_holes(variant)
    holes = all_holes(sensor_sites)
    board_x0, board_y0, board_x1, board_y1 = board_bounds(holes)

    usb_half = USB_CUT_WIDTH_MM * 0.5
    usb_cut = RectCut(-usb_half, board_y0, usb_half, USB_CUT_NORTH_Y_MM)
    mesh.extend(
        plate_with_holes_tris(
            board_x0,
            board_y0,
            board_x1,
            board_y1,
            0.0,
            BASE_THICKNESS_MM,
            holes,
            (usb_cut,),
        )
    )

    def add_feature_box(box: BoxSolid) -> None:
        box_holes = holes_for_box(box, holes)
        if box_holes:
            mesh.extend(
                plate_with_holes_tris(
                    box.x0,
                    box.y0,
                    box.x1,
                    box.y1,
                    box.z0,
                    box.z1,
                    box_holes,
                )
            )
        else:
            mesh.extend(box_tris(box.x0, box.y0, box.x1, box.y1, box.z0, box.z1))

    for box in build_unconnected_boxes(pads):
        add_feature_box(box)

    trace_boxes = build_trace_boxes(variant, pads)
    validate_trace_boxes(trace_boxes)
    for box in trace_boxes:
        add_feature_box(box)

    for box in build_emboss_boxes(variant):
        add_feature_box(box)

    return mesh


DEFAULT_OUT_DIR = (
    Path(__file__).resolve().parent.parent / "thermo/onboard/hardware/pico2w/hat"
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=DEFAULT_OUT_DIR,
        help="directory for output STL files",
    )
    args = parser.parse_args()
    out_dir = args.out_dir.resolve()
    for variant in VARIANTS:
        out_path = out_dir / f"thermo-pico2w-sensor-hat-v1-{variant.name}.stl"
        mesh = build_mesh(variant)
        mesh.write_ascii_stl(
            out_path, f"thermo_pico2w_sensor_hat_v1_{variant.name.replace('-', '_')}"
        )
        if variant.legacy_alias:
            legacy_path = out_dir / "thermo-pico2w-sensor-hat-v1.stl"
            mesh.write_ascii_stl(legacy_path, "thermo_pico2w_sensor_hat_v1")
            print(f"Wrote {legacy_path}")
        tri_count = len(mesh.triangles)
        print(f"Wrote {out_path}")
        print(f"Variant: {variant.name}")
        print(f"Triangles: {tri_count}")
    print(f"Base thickness: {BASE_THICKNESS_MM:.3f} mm (1/8 in)")
    print(f"Unconnected raise: {UNCONNECTED_RAISE_MM:.3f} mm")
    print(f"Trace raise: {TRACE_RAISE_MM:.3f} mm (1/8 in)")
    print(f"Trace width: {TRACE_WIDTH_MM:.3f} mm")
    print(f"Pico pad width: {PICO_PAD_WIDTH_MM:.3f} mm")
    print(f"Sensor pad width: {SENSOR_PAD_WIDTH_MM:.3f} mm")
    print("Pins routed: GP4 SDA, GP5 SCL, GP14 IR TX, GP15 IR RX, 3V3, GND")


if __name__ == "__main__":
    main()
