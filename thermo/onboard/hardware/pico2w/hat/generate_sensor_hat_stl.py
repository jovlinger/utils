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

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, List, Sequence, Tuple

Vec3 = Tuple[float, float, float]
Tri = Tuple[Vec3, Vec3, Vec3]

# 1/8 inch board and raised copper-tape traces
INCH_MM = 25.4
BASE_THICKNESS_MM = INCH_MM / 8.0
TRACE_RAISE_MM = INCH_MM / 8.0
PIN_HOLE_DIAMETER_MM = 1.1
MOUNT_HOLE_DIAMETER_MM = 2.2
SENSOR_HOLE_DIAMETER_MM = 1.1
GRID_MM = 0.5
TRACE_WIDTH_MM = 2.0
RAIL_WIDTH_MM = 2.8
LABEL_DEPTH_MM = 0.35
LABEL_HEIGHT_MM = 0.8

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
PIN_3V3_B = 39
PIN_GND_A = 3
PIN_GND_B = 8

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


class Mesh:
    def __init__(self) -> None:
        self.triangles: List[Tri] = []

    def extend(self, tris: Iterable[Tri]) -> None:
        self.triangles.extend(tris)

    def write_ascii_stl(self, path: Path, name: str) -> None:
        lines: List[str] = [f"solid {name}"]
        for a, b, c in self.triangles:
            normal = _normal(a, b, c)
            lines.append(f"  facet normal {normal[0]:.6f} {normal[1]:.6f} {normal[2]:.6f}")
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


def box_tris(x0: float, y0: float, x1: float, y1: float, z0: float, z1: float) -> List[Tri]:
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
                            ((fixed_coord, var, z0), (fixed_coord, vnext, z0), (fixed_coord, vnext, z1)),
                            ((fixed_coord, var, z0), (fixed_coord, vnext, z1), (fixed_coord, var, z1)),
                        ]
                    )
                else:
                    tris.extend(
                        [
                            ((fixed_coord, var, z1), (fixed_coord, vnext, z1), (fixed_coord, vnext, z0)),
                            ((fixed_coord, var, z1), (fixed_coord, vnext, z0), (fixed_coord, var, z0)),
                        ]
                    )
            else:
                if outward == "neg":
                    tris.extend(
                        [
                            ((var, fixed_coord, z0), (vnext, fixed_coord, z0), (vnext, fixed_coord, z1)),
                            ((var, fixed_coord, z0), (vnext, fixed_coord, z1), (var, fixed_coord, z1)),
                        ]
                    )
                else:
                    tris.extend(
                        [
                            ((var, fixed_coord, z1), (vnext, fixed_coord, z1), (vnext, fixed_coord, z0)),
                            ((var, fixed_coord, z1), (vnext, fixed_coord, z0), (var, fixed_coord, z0)),
                        ]
                    )
            var = vnext

    edge_strip(x0, y0, y1, "x", "neg")
    edge_strip(x1, y0, y1, "x", "pos")
    edge_strip(y0, x0, x1, "y", "neg")
    edge_strip(y1, x0, x1, "y", "pos")
    return tris


def manhattan_path(
    p0: Tuple[float, float], p1: Tuple[float, float]
) -> List[Tuple[float, float]]:
    x0, y0 = p0
    x1, y1 = p1
    if abs(x0 - x1) < 1e-6 and abs(y0 - y1) < 1e-6:
        return [(x0, y0)]
    return [(x0, y0), (x1, y0), (x1, y1)]


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
            boxes.append(BoxSolid(xa - half, y_lo - half, xa + half, y_hi + half, z0, z1, label))
        else:
            x_lo, x_hi = (xa, xb) if xa <= xb else (xb, xa)
            boxes.append(BoxSolid(x_lo - half, ya - half, x_hi + half, ya + half, z0, z1, label))
    return boxes


def subtract_label(box: BoxSolid, text: str) -> Tuple[BoxSolid, BoxSolid | None]:
    if not text:
        return box, None
    cx = (box.x0 + box.x1) * 0.5
    cy = (box.y0 + box.y1) * 0.5
    length = max(box.x1 - box.x0, box.y1 - box.y0)
    lw = min(length * 0.75, len(text) * LABEL_HEIGHT_MM * 0.65)
    lh = LABEL_HEIGHT_MM
    recess = BoxSolid(
        cx - lw * 0.5,
        cy - lh * 0.5,
        cx + lw * 0.5,
        cy + lh * 0.5,
        box.z1 - LABEL_DEPTH_MM,
        box.z1,
        None,
    )
    return box, recess


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


def sensor_module_holes() -> Tuple[List[Tuple[float, float]], dict[str, Tuple[float, float]]]:
    """Return all sensor pad centers and named signal pad targets."""
    # AHT20 4-pin row between header rows (VCC, SDA, SCL, GND left-to-right).
    aht_y = -10.0
    aht_x0 = -3.81
    aht: List[Tuple[float, float]] = []
    for i in range(4):
        aht.append((aht_x0 + i * PITCH_MM, aht_y))
    pads = {
        "aht_vcc": aht[0],
        "aht_sda": aht[1],
        "aht_scl": aht[2],
        "aht_gnd": aht[3],
        "irtx_vcc": (-14.0, 2.0),
        "irtx_dat": (-14.0, 4.54),
        "irtx_gnd": (-14.0, 7.08),
        "irrx_vcc": (14.0, 2.0),
        "irrx_out": (14.0, 4.54),
        "irrx_gnd": (14.0, 7.08),
    }
    sites: List[Tuple[float, float]] = list(aht)
    for key in ("irtx_vcc", "irtx_dat", "irtx_gnd", "irrx_vcc", "irrx_out", "irrx_gnd"):
        sites.append(pads[key])
    return sites, pads


def build_trace_boxes(pads: dict[str, Tuple[float, float]]) -> List[BoxSolid]:
    z0 = BASE_THICKNESS_MM
    z1 = BASE_THICKNESS_MM + TRACE_RAISE_MM

    def pt(pin: int) -> Tuple[float, float]:
        return PICO_PADS_MM[pin]

    rail_y1 = 14.0
    rails: List[BoxSolid] = [
        BoxSolid(-2.9, -24.0, -0.1, rail_y1, z0, z1, "3V3"),
        BoxSolid(0.1, -24.0, 2.9, rail_y1, z0, z1, "GND"),
    ]

    def trace(points: Sequence[Tuple[float, float]], label: str) -> List[BoxSolid]:
        return trace_boxes_from_path(points, TRACE_WIDTH_MM, z0, z1, label)

    boxes: List[BoxSolid] = []
    boxes.extend(rails)

    boxes.extend(
        trace(
            manhattan_path(pt(PIN_3V3_A), pads["aht_vcc"])
            + manhattan_path(pads["aht_vcc"], pads["irtx_vcc"])[1:]
            + manhattan_path(pads["irtx_vcc"], pads["irrx_vcc"])[1:],
            "3V3",
        )
    )
    boxes.extend(
        trace(
            manhattan_path(pt(PIN_GND_A), pads["aht_gnd"])
            + manhattan_path(pads["aht_gnd"], pads["irtx_gnd"])[1:]
            + manhattan_path(pads["irtx_gnd"], pads["irrx_gnd"])[1:],
            "GND",
        )
    )
    boxes.extend(trace(manhattan_path(pt(PIN_GP4), pads["aht_sda"]), "GP4"))
    boxes.extend(trace(manhattan_path(pt(PIN_GP5), pads["aht_scl"]), "GP5"))
    boxes.extend(trace(manhattan_path(pt(PIN_GP14), pads["irtx_dat"]), "GP14"))
    boxes.extend(trace(manhattan_path(pt(PIN_GP15), pads["irrx_out"]), "GP15"))

    boxes.extend(trace(manhattan_path(pt(PIN_3V3_B), (-1.4, -20.0)), "3V3"))
    boxes.extend(trace(manhattan_path(pt(PIN_GND_B), (1.4, -20.0)), "GND"))

    return boxes


def build_mesh() -> Mesh:
    mesh = Mesh()
    sensor_sites, pads = sensor_module_holes()
    holes = all_holes(sensor_sites)

    board_x0, board_x1 = -20.0, 20.0
    board_y0, board_y1 = -32.0, 30.0

    usb_cut = RectCut(-7.0, -30.5, 7.0, -25.5)
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

    trace_boxes = build_trace_boxes(pads)
    for box in trace_boxes:
        solid, recess = subtract_label(box, box.label or "")
        mesh.extend(box_tris(solid.x0, solid.y0, solid.x1, solid.y1, solid.z0, solid.z1))
        if recess is not None:
            mesh.extend(
                box_tris(recess.x0, recess.y0, recess.x1, recess.y1, recess.z0, recess.z1)
            )

    return mesh


def main() -> None:
    out_dir = Path(__file__).resolve().parent
    out_path = out_dir / "thermo-pico2w-sensor-hat-v1.stl"
    mesh = build_mesh()
    mesh.write_ascii_stl(out_path, "thermo_pico2w_sensor_hat_v1")
    tri_count = len(mesh.triangles)
    print(f"Wrote {out_path}")
    print(f"Triangles: {tri_count}")
    print(f"Base thickness: {BASE_THICKNESS_MM:.3f} mm (1/8 in)")
    print(f"Trace raise: {TRACE_RAISE_MM:.3f} mm (1/8 in)")
    print("Pins routed: GP4 SDA, GP5 SCL, GP14 IR TX, GP15 IR RX, 3V3, GND")


if __name__ == "__main__":
    main()
