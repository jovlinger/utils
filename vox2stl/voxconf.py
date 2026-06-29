#!/usr/bin/env python3
"""Load named vox2stl geometry profiles from .conf files."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, FrozenSet, Mapping, MutableMapping, Sequence, Tuple, Union

CONFIG_DIR = Path(__file__).resolve().parent

INCLUDE_RE = re.compile(r"^include\s+([A-Za-z0-9_.-]+)\s*$")
ASSIGN_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$")

FLOAT_KEYS: FrozenSet[str] = frozenset(
    {
        "unit_mm",
        "trace_width_frac",
        "adjacent_isolation_gap_frac",
        "pin_outside_frac",
        "leg_outside_frac",
        "tile_overlap_frac",
        "cond_lig_frac",
        "isol_lig_frac",
        "trace_hole_clearance_frac",
        "grid_frac",
        "hole_oval_minor_frac",
        "hole_oval_band_mm",
        "label_recess_frac",
        "label_height_frac",
        "label_stroke_frac",
        "layer_thickness_mm",
        "base_z0_mm",
        "base_z1_mm",
        "trace_z0_mm",
        "trace_z1_mm",
        "pin_hole_diameter_mm",
        "device_hole_diameter_mm",
    }
)
INT_KEYS: FrozenSet[str] = frozenset(
    {
        "hole_void_grid_divisor",
        "label_tile_max_triangles",
        "label_raster_size",
        "label_blur_passes",
        "label_blur_radius",
        "max_vertex_valence",
    }
)
TUPLE_FLOAT_KEYS: FrozenSet[str] = frozenset({"hole_oval_z_fracs"})
OPTIONAL_FLOAT_KEYS: FrozenSet[str] = frozenset({"base_z1_mm", "trace_z0_mm", "trace_z1_mm"})

KNOWN_KEYS: FrozenSet[str] = FLOAT_KEYS | INT_KEYS | TUPLE_FLOAT_KEYS
REQUIRED_KEYS: FrozenSet[str] = KNOWN_KEYS - OPTIONAL_FLOAT_KEYS


@dataclass(frozen=True)
class VoxProfile:
    unit_mm: float
    trace_width_frac: float
    adjacent_isolation_gap_frac: float
    pin_outside_frac: float
    leg_outside_frac: float
    tile_overlap_frac: float
    cond_lig_frac: float
    isol_lig_frac: float
    trace_hole_clearance_frac: float
    grid_frac: float
    hole_oval_minor_frac: float
    hole_oval_band_mm: float
    hole_oval_z_fracs: Tuple[float, ...]
    hole_void_grid_divisor: int
    label_recess_frac: float
    label_height_frac: float
    label_tile_max_triangles: int
    label_raster_size: int
    label_stroke_frac: float
    label_blur_passes: int
    label_blur_radius: int
    max_vertex_valence: int
    layer_thickness_mm: float
    base_z0_mm: float
    pin_hole_diameter_mm: float
    device_hole_diameter_mm: float
    base_z1_mm: float | None = None
    trace_z0_mm: float | None = None
    trace_z1_mm: float | None = None

    @property
    def resolved_base_z1_mm(self) -> float:
        if self.base_z1_mm is not None:
            return self.base_z1_mm
        return self.base_z0_mm + self.layer_thickness_mm

    @property
    def resolved_trace_z0_mm(self) -> float:
        if self.trace_z0_mm is not None:
            return self.trace_z0_mm
        return self.resolved_base_z1_mm

    @property
    def resolved_trace_z1_mm(self) -> float:
        if self.trace_z1_mm is not None:
            return self.trace_z1_mm
        return self.resolved_trace_z0_mm + self.layer_thickness_mm

    @property
    def trace_width_mm(self) -> float:
        return self.trace_width_frac * self.unit_mm

    @property
    def adjacent_isolation_gap_mm(self) -> float:
        return self.adjacent_isolation_gap_frac * self.unit_mm

    @property
    def pad_width_mm(self) -> float:
        return self.pin_outside_frac * self.unit_mm

    @property
    def device_pad_width_mm(self) -> float:
        return self.leg_outside_frac * self.unit_mm

    @property
    def overlap_mm(self) -> float:
        return self.tile_overlap_frac * self.unit_mm

    @property
    def cond_lig_mm(self) -> float:
        return self.cond_lig_frac * self.unit_mm

    @property
    def isol_lig_mm(self) -> float:
        return self.isol_lig_frac * self.unit_mm

    @property
    def trace_hole_clearance_mm(self) -> float:
        return self.trace_hole_clearance_frac * self.unit_mm

    @property
    def label_recess_mm(self) -> float:
        return self.label_recess_frac * self.unit_mm

    @property
    def label_height_mm(self) -> float:
        return self.label_height_frac * self.unit_mm

    @property
    def grid_mm(self) -> float:
        return self.grid_frac * self.unit_mm


def _config_path(name: str) -> Path:
    basename = name
    if basename.endswith(".conf"):
        basename = basename[: -len(".conf")]
    return CONFIG_DIR / f"{basename}.conf"


def _parse_float(raw_value: str, key: str, source: str) -> float:
    try:
        value = float(raw_value)
    except ValueError as exc:
        raise ValueError(f"{source}: {key} must be a number, got {raw_value!r}") from exc
    return value


def _parse_int(raw_value: str, key: str, source: str) -> int:
    try:
        value = int(raw_value, 10)
    except ValueError as exc:
        raise ValueError(f"{source}: {key} must be an integer, got {raw_value!r}") from exc
    return value


def _parse_tuple_floats(raw_value: str, key: str, source: str) -> Tuple[float, ...]:
    parts = [part.strip() for part in raw_value.split(",") if part.strip()]
    if not parts:
        raise ValueError(f"{source}: {key} must list at least one number")
    return tuple(_parse_float(part, key, source) for part in parts)


def _coerce_value(key: str, raw_value: str, source: str) -> Union[float, int, Tuple[float, ...]]:
    if key in FLOAT_KEYS:
        return _parse_float(raw_value, key, source)
    if key in INT_KEYS:
        return _parse_int(raw_value, key, source)
    if key in TUPLE_FLOAT_KEYS:
        return _parse_tuple_floats(raw_value, key, source)
    raise ValueError(f"{source}: unknown config key {key!r}")


def _parse_config_text(text: str, source: str) -> Tuple[Tuple[str, ...], Dict[str, Union[float, int, Tuple[float, ...]]]]:
    includes: list[str] = []
    values: Dict[str, Union[float, int, Tuple[float, ...]]] = {}
    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        include_match = INCLUDE_RE.match(line)
        if include_match is not None:
            includes.append(include_match.group(1))
            continue
        assign_match = ASSIGN_RE.match(line)
        if assign_match is None:
            raise ValueError(f"{source}:{line_number}: malformed config line {raw_line!r}")
        key = assign_match.group(1)
        if key not in KNOWN_KEYS:
            raise ValueError(f"{source}:{line_number}: unknown config key {key!r}")
        values[key] = _coerce_value(key, assign_match.group(2).strip(), f"{source}:{line_number}")
    return tuple(includes), values


def _merge_values(
    base: MutableMapping[str, Union[float, int, Tuple[float, ...]]],
    overrides: Mapping[str, Union[float, int, Tuple[float, ...]]],
) -> None:
    base.update(overrides)


def _resolve_config(
    name: str,
    *,
    stack: Tuple[str, ...] = (),
) -> Dict[str, Union[float, int, Tuple[float, ...]]]:
    basename = name
    if basename.endswith(".conf"):
        basename = basename[: -len(".conf")]
    if basename in stack:
        chain = " -> ".join((*stack, basename))
        raise ValueError(f"circular config include: {chain}")
    path = _config_path(basename)
    if not path.is_file():
        raise ValueError(f"missing config file {path}")
    includes, values = _parse_config_text(path.read_text(encoding="ascii"), str(path))
    merged: Dict[str, Union[float, int, Tuple[float, ...]]] = {}
    for include_name in includes:
        included = _resolve_config(include_name, stack=(*stack, basename))
        _merge_values(merged, included)
    _merge_values(merged, values)
    return merged


def _require_key(
    values: Mapping[str, Union[float, int, Tuple[float, ...]]],
    key: str,
    source: str,
) -> Union[float, int, Tuple[float, ...]]:
    if key not in values:
        raise ValueError(f"{source}: missing required config key {key!r}")
    return values[key]


def load_config(name: str = "default") -> VoxProfile:
    """Load a named profile, resolving includes and overrides in order."""

    source = _config_path(name)
    values = _resolve_config(name)
    missing = sorted(REQUIRED_KEYS - set(values))
    if missing:
        raise ValueError(f"{source}: missing required config key(s): {', '.join(missing)}")

    def float_key(key: str) -> float:
        value = _require_key(values, key, str(source))
        if not isinstance(value, float):
            raise ValueError(f"{source}: {key} must be a number")
        return value

    def int_key(key: str) -> int:
        value = _require_key(values, key, str(source))
        if not isinstance(value, int):
            raise ValueError(f"{source}: {key} must be an integer")
        return value

    def tuple_key(key: str) -> Tuple[float, ...]:
        value = _require_key(values, key, str(source))
        if not isinstance(value, tuple):
            raise ValueError(f"{source}: {key} must be a comma-separated list of numbers")
        return value

    optional_float = lambda key: float(values[key]) if key in values and isinstance(values[key], float) else None

    return VoxProfile(
        unit_mm=float_key("unit_mm"),
        trace_width_frac=float_key("trace_width_frac"),
        adjacent_isolation_gap_frac=float_key("adjacent_isolation_gap_frac"),
        pin_outside_frac=float_key("pin_outside_frac"),
        leg_outside_frac=float_key("leg_outside_frac"),
        tile_overlap_frac=float_key("tile_overlap_frac"),
        cond_lig_frac=float_key("cond_lig_frac"),
        isol_lig_frac=float_key("isol_lig_frac"),
        trace_hole_clearance_frac=float_key("trace_hole_clearance_frac"),
        grid_frac=float_key("grid_frac"),
        hole_oval_minor_frac=float_key("hole_oval_minor_frac"),
        hole_oval_band_mm=float_key("hole_oval_band_mm"),
        hole_oval_z_fracs=tuple_key("hole_oval_z_fracs"),
        hole_void_grid_divisor=int_key("hole_void_grid_divisor"),
        label_recess_frac=float_key("label_recess_frac"),
        label_height_frac=float_key("label_height_frac"),
        label_tile_max_triangles=int_key("label_tile_max_triangles"),
        label_raster_size=int_key("label_raster_size"),
        label_stroke_frac=float_key("label_stroke_frac"),
        label_blur_passes=int_key("label_blur_passes"),
        label_blur_radius=int_key("label_blur_radius"),
        max_vertex_valence=int_key("max_vertex_valence"),
        layer_thickness_mm=float_key("layer_thickness_mm"),
        base_z0_mm=float_key("base_z0_mm"),
        pin_hole_diameter_mm=float_key("pin_hole_diameter_mm"),
        device_hole_diameter_mm=float_key("device_hole_diameter_mm"),
        base_z1_mm=optional_float("base_z1_mm"),
        trace_z0_mm=optional_float("trace_z0_mm"),
        trace_z1_mm=optional_float("trace_z1_mm"),
    )
