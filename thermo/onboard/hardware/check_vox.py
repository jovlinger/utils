#!/usr/bin/env python3
"""Validate HAT text voxel design files.

VOX files are treated as human-readable binary design artifacts and may use
UTF-8 box-drawing glyphs in the checked diagram window.
"""

from __future__ import annotations

import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

PIN_PAD_CHAR = "*"
LEG_PAD_CHAR = "O"

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

BOX_CHARS: FrozenSet[str] = frozenset(
    {
        BOX_UL,
        BOX_UR,
        BOX_LL,
        BOX_LR,
        BOX_T_LEFT,
        BOX_T_RIGHT,
        BOX_T_DOWN,
        BOX_T_UP,
        BOX_CROSS,
        BOX_H,
        BOX_V,
    }
)
COPPER_CHARS: FrozenSet[str] = frozenset({PIN_PAD_CHAR, LEG_PAD_CHAR, "-", "|", "+"}) | BOX_CHARS
PAD_CHARS: FrozenSet[str] = frozenset({PIN_PAD_CHAR, LEG_PAD_CHAR})
ARMS_BY_CHAR: Mapping[str, FrozenSet[str]] = {
    PIN_PAD_CHAR: frozenset({"N", "E", "S", "W"}),
    LEG_PAD_CHAR: frozenset({"N", "E", "S", "W"}),
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

ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzX*O.-|+/\\?T^v<> +-")
ALLOWED_CHARS.update(BOX_CHARS)
REQUIRED_LAYERS = ("base", "trace")
LAYER_HEADER_RE = re.compile(r"^layer\s+([A-Za-z0-9_-]+)\s+\((\d+),\s*(\d+),\s*(\d+)\)$")
ROW_LABEL_RE = re.compile(r"^\s*(\S+)")
BOX_ASSERT_CHARS = "".join(re.escape(char) for char in sorted(BOX_CHARS))
TRACE_COL_ASSERT_RE = re.compile(r"c(\d+)=(-\*|\*-|\||\+|-|[" + BOX_ASSERT_CHARS + r"])")
TRACE_NET_ASSERT_RE = re.compile(r"\.c(\d+)\s*=\s*([A-Za-z0-9_:-]+)")
INTENT_NET_RE = re.compile(r"^#\s*net\s+(\S+)\s+(.+)$")
INTENT_DISJOINT_RE = re.compile(r"^#\s*disjoint\s+(.+)$")
INTENT_ENDPOINT_RE = re.compile(r"^([A-Za-z0-9_:-]+)\.c(\d+)$")


@dataclass(frozen=True)
class Layer:
    name: str
    offset: int
    width: int
    height: int
    rows: List[str]


@dataclass(frozen=True)
class RowExpectation:
    """Expected */O pad columns for one labeled row."""

    label: str
    pin_cols: FrozenSet[int]
    o_cols: FrozenSet[int]


@dataclass(frozen=True)
class BoardVoxProfile:
    """Board-specific validation details layered on the generic checker."""

    name: str
    path_part: str
    unit_mm: float
    expected_inner_cols: int
    row_layouts: Mapping[str, Tuple[RowExpectation, ...]]
    crowding_hints: Mapping[str, str]


@dataclass(frozen=True)
class CellRef:
    """Trace grid cell: row label, 1-based duplicate index, column cN."""

    row_label: str
    occurrence: int
    col: int


@dataclass
class TraceIntents:
    nets: Dict[str, List[CellRef]] = field(default_factory=dict)
    disjoint: List[Tuple[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class TraceNetAssertion:
    """Expected net for one trace-row cell, parsed from a row comment."""

    row_index: int
    row_label: str
    col: int
    net_name: str


def _row(label: str, pin_cols: FrozenSet[int], o_cols: FrozenSet[int]) -> RowExpectation:
    return RowExpectation(label=label, pin_cols=pin_cols, o_cols=o_cols)


_PICO_HEADER_PINS: FrozenSet[int] = frozenset({1, 8})

PICO_UP_SIDE_LAYOUT: Tuple[RowExpectation, ...] = (
    _row("GP15", _PICO_HEADER_PINS, frozenset()),
    _row("GP14", _PICO_HEADER_PINS, frozenset()),
    _row("GND", _PICO_HEADER_PINS, frozenset()),
    _row("GP13", _PICO_HEADER_PINS, frozenset({4, 5, 6})),
    _row("GP12", _PICO_HEADER_PINS, frozenset()),
    _row("GP11", _PICO_HEADER_PINS, frozenset()),
    _row("GP10", _PICO_HEADER_PINS, frozenset({4, 5, 6})),
    _row("GP9", _PICO_HEADER_PINS, frozenset()),
    _row("GP8", _PICO_HEADER_PINS, frozenset()),
    _row("GP7", _PICO_HEADER_PINS, frozenset()),
    _row("GP6", _PICO_HEADER_PINS, frozenset()),
    _row("GP5", _PICO_HEADER_PINS, frozenset()),
    _row("GP4", _PICO_HEADER_PINS, frozenset({3, 4, 5, 6})),
    _row("GP3", _PICO_HEADER_PINS, frozenset()),
    _row("GP2", _PICO_HEADER_PINS, frozenset()),
    _row("GP1", _PICO_HEADER_PINS, frozenset()),
    _row("GP0", _PICO_HEADER_PINS, frozenset()),
)

PICO_SIDE_LAYOUT: Tuple[RowExpectation, ...] = (
    _row("P20", _PICO_HEADER_PINS, frozenset()),
    _row("P19", _PICO_HEADER_PINS, frozenset()),
    _row("P18", _PICO_HEADER_PINS, frozenset()),
    _row("P17", _PICO_HEADER_PINS, frozenset({3, 4, 5})),
    _row("P16", _PICO_HEADER_PINS, frozenset()),
    _row("P15", _PICO_HEADER_PINS, frozenset()),
    _row("P14", _PICO_HEADER_PINS, frozenset({3, 4, 5})),
    _row("P13", _PICO_HEADER_PINS, frozenset()),
    _row("P12", _PICO_HEADER_PINS, frozenset()),
    _row("P11", _PICO_HEADER_PINS, frozenset()),
    _row("P10", _PICO_HEADER_PINS, frozenset()),
    _row("P9", _PICO_HEADER_PINS, frozenset()),
    _row("P8", _PICO_HEADER_PINS, frozenset()),
    _row("P7", _PICO_HEADER_PINS, frozenset()),
    _row("P6", _PICO_HEADER_PINS, frozenset({3, 4, 5, 6})),
    _row("P5", _PICO_HEADER_PINS, frozenset()),
    _row("P4", _PICO_HEADER_PINS, frozenset()),
    _row("P3", _PICO_HEADER_PINS, frozenset()),
    _row("P2", _PICO_HEADER_PINS, frozenset()),
    _row("P1", _PICO_HEADER_PINS, frozenset()),
)

PICO2W_PROFILE = BoardVoxProfile(
    name="pico2w",
    path_part="pico2w",
    unit_mm=2.54,
    expected_inner_cols=8,
    row_layouts={
        "up-side": PICO_UP_SIDE_LAYOUT,
        "pico-side": PICO_SIDE_LAYOUT,
    },
    crowding_hints={
        "up-side": "on up-side: shift module legs and center rails one column east",
        "pico-side": "pico-side layout is separate; review crowding on its own terms",
    },
)

BOARD_PROFILES: Tuple[BoardVoxProfile, ...] = (PICO2W_PROFILE,)


def board_profile_for_path(path: Path) -> Optional[BoardVoxProfile]:
    parts = set(path.parts)
    for profile in BOARD_PROFILES:
        if profile.path_part in parts:
            return profile
    return None


def inner_column_count(layer: Layer) -> int:
    return max(0, layer.width - 2)


def col_label(col_index: int, profile: Optional[BoardVoxProfile], layer: Optional[Layer] = None) -> str:
    name = f"c{col_index}"
    if profile is None:
        return name
    inner_cols = profile.expected_inner_cols
    if layer is not None:
        inner_cols = inner_column_count(layer)
    center = (inner_cols + 1) * 0.5
    x_mm = (col_index - center) * profile.unit_mm
    return f"{name} (x={x_mm:.2f})"


def checked_window(layer: Layer, row: str) -> str:
    start = max(layer.offset - 1, 0)
    end = layer.offset + layer.width + 1
    return row.ljust(end)[start:end]


def design_window(layer: Layer, row: str) -> str:
    end = layer.offset + layer.width
    return row.ljust(end)[layer.offset:end]


def row_label(row: str) -> Optional[str]:
    match = ROW_LABEL_RE.match(row)
    if match is None:
        return None
    token = match.group(1)
    if token.startswith("X") or token == ".":
        return None
    return token


def read_layers(path: Path) -> Dict[str, Layer]:
    layers: Dict[str, Layer] = {}
    current: Optional[Layer] = None
    for line_no, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw_line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        match = LAYER_HEADER_RE.match(line)
        if match:
            name = match.group(1)
            if name in layers:
                raise ValueError(f"{path}:{line_no}: duplicate layer {name!r}")
            current = Layer(
                name=name,
                offset=int(match.group(2)),
                width=int(match.group(3)),
                height=int(match.group(4)),
                rows=[],
            )
            layers[name] = current
            continue
        if line.startswith("layer "):
            raise ValueError(f"{path}:{line_no}: invalid layer header")
        if current is None:
            raise ValueError(f"{path}:{line_no}: content before first layer")
        window = checked_window(current, line)
        bad_chars = sorted(set(window) - ALLOWED_CHARS)
        if bad_chars:
            raise ValueError(
                f"{path}:{line_no}: invalid chars in checked window {''.join(bad_chars)!r}"
            )
        current.rows.append(line)
    return layers


def find_pad_columns(window: str) -> Tuple[FrozenSet[int], FrozenSet[int]]:
    pin_cols: set[int] = set()
    o_cols: set[int] = set()
    for index, char in enumerate(window):
        if char == PIN_PAD_CHAR:
            pin_cols.add(index)
        elif char == LEG_PAD_CHAR:
            o_cols.add(index)
    return frozenset(pin_cols), frozenset(o_cols)


def validate_pin_layout(
    path: Path,
    layer_name: str,
    layer: Layer,
    expectations: Sequence[RowExpectation],
    profile: Optional[BoardVoxProfile],
) -> None:
    by_label: Dict[str, RowExpectation] = {item.label: item for item in expectations}
    seen: set[str] = set()
    for row_index, row in enumerate(layer.rows, 1):
        label = row_label(row)
        if label is None or label not in by_label:
            continue
        seen.add(label)
        expect = by_label[label]
        window = design_window(layer, row)
        pin_cols, o_cols = find_pad_columns(window)
        if pin_cols != expect.pin_cols:
            expected = ", ".join(col_label(c, profile, layer) for c in sorted(expect.pin_cols))
            raise ValueError(
                f"{path}: layer {layer_name!r} row {row_index} ({label}): "
                f"{PIN_PAD_CHAR} columns {sorted(pin_cols)} != expected "
                f"{sorted(expect.pin_cols)} ({expected})"
            )
        if o_cols != expect.o_cols:
            expected = ", ".join(col_label(c, profile, layer) for c in sorted(expect.o_cols))
            raise ValueError(
                f"{path}: layer {layer_name!r} row {row_index} ({label}): "
                f"O columns {sorted(o_cols)} != expected {sorted(expect.o_cols)} ({expected})"
            )
        extras = (pin_cols | o_cols) - (expect.pin_cols | expect.o_cols)
        if extras:
            raise ValueError(
                f"{path}: layer {layer_name!r} row {row_index} ({label}): "
                f"unexpected pads at {sorted(extras)}"
            )
    missing = set(by_label) - seen
    if missing:
        raise ValueError(f"{path}: layer {layer_name!r} missing rows: {sorted(missing)}")


def extract_col_assertions(row: str) -> List[Tuple[int, str]]:
    return [(int(match.group(1)), match.group(2)) for match in TRACE_COL_ASSERT_RE.finditer(row)]


def extract_trace_net_assertions(trace: Layer, max_col: int) -> List[TraceNetAssertion]:
    assertions: List[TraceNetAssertion] = []
    for row_i, row in enumerate(trace.rows):
        label = row_label(row) or f"row {row_i + 1}"
        for match in TRACE_NET_ASSERT_RE.finditer(row):
            col = int(match.group(1))
            if col < 1 or col > max_col:
                raise ValueError(
                    f"trace row {row_i + 1} ({label}) .c{col}: "
                    f"column must be 1..{max_col}"
                )
            assertions.append(
                TraceNetAssertion(
                    row_index=row_i,
                    row_label=label,
                    col=col,
                    net_name=match.group(2),
                )
            )
    return assertions


def validate_col_assertion(window: str, max_col: int, col: int, token: str) -> Optional[str]:
    if col < 1 or col > max_col:
        return f"column {col} out of design range 1..{max_col}"
    if token in {"|", "+", "-"} | BOX_CHARS:
        actual = window[col]
        if actual != token:
            return f"expected {token!r}, got {actual!r}"
        return None
    if token == "*-":
        if col >= max_col:
            return "*- needs a column east of the pad"
        if window[col] != PIN_PAD_CHAR or window[col + 1] != "-":
            return f"expected *-, got {window[col : col + 2]!r}"
        return None
    if token == "-*":
        if col <= 1:
            return "-* needs a column west of the pad"
        if window[col - 1] != "-" or window[col] != PIN_PAD_CHAR:
            return f"expected -*, got {window[col - 1 : col + 1]!r}"
        return None
    return f"unknown assertion token {token!r}"


def parse_intent_endpoint(token: str, max_col: int) -> CellRef:
    match = INTENT_ENDPOINT_RE.match(token.strip())
    if match is None:
        raise ValueError(f"invalid intent endpoint {token!r} (want LABEL.cN or LABEL:N.cN)")
    label_token = match.group(1)
    col = int(match.group(2))
    if col < 1 or col > max_col:
        raise ValueError(f"intent endpoint {token!r}: column must be 1..{max_col}")
    occurrence = 1
    row_name = label_token
    if ":" in label_token:
        base, _, index_text = label_token.partition(":")
        if not index_text.isdigit():
            raise ValueError(f"intent endpoint {token!r}: row occurrence must be digits after ':'")
        occurrence = int(index_text)
        row_name = base
    return CellRef(row_label=row_name, occurrence=occurrence, col=col)


def read_trace_intents(path: Path, max_col: int) -> TraceIntents:
    intents = TraceIntents()
    in_block = False
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line == "# trace intents":
            in_block = True
            continue
        if not in_block:
            continue
        if not line.startswith("#"):
            break
        body = line[1:].strip()
        if not body or body.startswith("trace intents") or "--" in body:
            continue
        net_match = INTENT_NET_RE.match(line)
        if net_match:
            name = net_match.group(1)
            tokens = net_match.group(2).split()
            try:
                endpoints = [parse_intent_endpoint(token, max_col) for token in tokens]
            except ValueError:
                continue
            intents.nets[name] = endpoints
            continue
        disjoint_match = INTENT_DISJOINT_RE.match(line)
        if disjoint_match:
            names = disjoint_match.group(1).split()
            if len(names) != 2:
                raise ValueError(f"disjoint expects two net names, got {names!r}")
            intents.disjoint.append((names[0], names[1]))
    return intents


def build_row_label_index(trace: Layer) -> Dict[Tuple[str, int], int]:
    """Map (row_label, 1-based occurrence) to trace row index."""
    seen: Dict[str, int] = {}
    index: Dict[Tuple[str, int], int] = {}
    for row_index, row in enumerate(trace.rows):
        label = row_label(row)
        if label is None:
            continue
        seen[label] = seen.get(label, 0) + 1
        index[(label, seen[label])] = row_index
    return index


def resolve_cell_ref(
    path: Path,
    trace: Layer,
    ref: CellRef,
    row_index: Mapping[Tuple[str, int], int],
) -> Tuple[int, int]:
    key = (ref.row_label, ref.occurrence)
    if key not in row_index:
        raise ValueError(
            f"{path}: intent endpoint {ref.row_label}:{ref.occurrence}.c{ref.col} "
            f"row not found"
        )
    row_i = row_index[key]
    window = design_window(trace, trace.rows[row_i])
    char = window[ref.col]
    if char not in COPPER_CHARS:
        raise ValueError(
            f"{path}: intent endpoint {ref.row_label}:{ref.occurrence}.c{ref.col} "
            f"is {char!r}, not copper"
        )
    return row_i, ref.col


def horizontal_connects(left: str, right: str) -> bool:
    if left in PAD_CHARS and right in PAD_CHARS:
        return False
    return "E" in ARMS_BY_CHAR.get(left, frozenset()) and "W" in ARMS_BY_CHAR.get(
        right, frozenset()
    )


def vertical_connects(top: str, bottom: str) -> bool:
    if top in PAD_CHARS and bottom in PAD_CHARS:
        return False
    return "S" in ARMS_BY_CHAR.get(top, frozenset()) and "N" in ARMS_BY_CHAR.get(
        bottom, frozenset()
    )


def trace_char_at(trace: Layer, row_i: int, col: int) -> str:
    return design_window(trace, trace.rows[row_i])[col]


def flood_fill_components(trace: Layer, max_col: int) -> Dict[Tuple[int, int], int]:
    """Return (row_index, col) to component id for all copper cells."""
    components: Dict[Tuple[int, int], int] = {}
    next_id = 0
    height = len(trace.rows)
    for row_i in range(height):
        for col in range(1, max_col + 1):
            if (row_i, col) in components:
                continue
            char = trace_char_at(trace, row_i, col)
            if char not in COPPER_CHARS:
                continue
            queue: deque[Tuple[int, int]] = deque([(row_i, col)])
            components[(row_i, col)] = next_id
            while queue:
                row, current_col = queue.popleft()
                here = trace_char_at(trace, row, current_col)
                if current_col > 1:
                    left = trace_char_at(trace, row, current_col - 1)
                    if (row, current_col - 1) not in components and horizontal_connects(left, here):
                        components[(row, current_col - 1)] = next_id
                        queue.append((row, current_col - 1))
                if current_col < max_col:
                    right = trace_char_at(trace, row, current_col + 1)
                    if (row, current_col + 1) not in components and horizontal_connects(here, right):
                        components[(row, current_col + 1)] = next_id
                        queue.append((row, current_col + 1))
                if row > 0:
                    up = trace_char_at(trace, row - 1, current_col)
                    if (row - 1, current_col) not in components and vertical_connects(up, here):
                        components[(row - 1, current_col)] = next_id
                        queue.append((row - 1, current_col))
                if row + 1 < height:
                    down = trace_char_at(trace, row + 1, current_col)
                    if (row + 1, current_col) not in components and vertical_connects(here, down):
                        components[(row + 1, current_col)] = next_id
                        queue.append((row + 1, current_col))
            next_id += 1
    return components


def validate_module_leg_short_risk(path: Path, trace: Layer, max_col: int) -> None:
    """Fail when a bridge actually contacts both module O legs below it."""
    for row_i in range(len(trace.rows) - 1):
        upper_label = row_label(trace.rows[row_i]) or f"row {row_i + 1}"
        upper = design_window(trace, trace.rows[row_i])
        lower = design_window(trace, trace.rows[row_i + 1])
        for col in range(1, max_col):
            left = upper[col]
            right = upper[col + 1]
            if left not in COPPER_CHARS or right not in COPPER_CHARS:
                continue
            if not horizontal_connects(left, right):
                continue
            if (
                lower[col] == LEG_PAD_CHAR
                and lower[col + 1] == LEG_PAD_CHAR
                and vertical_connects(left, lower[col])
                and vertical_connects(right, lower[col + 1])
            ):
                raise ValueError(
                    f"{path}: trace row {row_i + 1} ({upper_label}) "
                    f"c{col}-c{col + 1} bridge contacts both module O legs on row below"
                )


def validate_trace_net_assertions(
    path: Path,
    trace: Layer,
    assertions: Sequence[TraceNetAssertion],
    components: Mapping[Tuple[int, int], int],
    endpoint_components: Mapping[str, Sequence[Tuple[CellRef, int]]],
) -> None:
    if not assertions:
        return
    errors: List[str] = []
    component_nets: Dict[int, List[str]] = {}
    for net_name, refs in endpoint_components.items():
        for _, comp in refs:
            component_nets.setdefault(comp, []).append(net_name)
    for assertion in assertions:
        if assertion.net_name not in endpoint_components:
            errors.append(
                f"{path}: trace row {assertion.row_index + 1} ({assertion.row_label}) "
                f".c{assertion.col}={assertion.net_name}: unknown net"
            )
            continue
        cell = (assertion.row_index, assertion.col)
        char = trace_char_at(trace, assertion.row_index, assertion.col)
        if char not in COPPER_CHARS:
            errors.append(
                f"{path}: trace row {assertion.row_index + 1} ({assertion.row_label}) "
                f".c{assertion.col}={assertion.net_name}: cell is {char!r}, not copper"
            )
            continue
        if cell not in components:
            errors.append(
                f"{path}: trace row {assertion.row_index + 1} ({assertion.row_label}) "
                f".c{assertion.col}={assertion.net_name}: cell is isolated copper"
            )
            continue
        actual_comp = components[cell]
        expected_comps = {comp for _, comp in endpoint_components[assertion.net_name]}
        if actual_comp in expected_comps:
            continue
        actual_names = sorted(set(component_nets.get(actual_comp, [])))
        actual = ", ".join(actual_names) if actual_names else f"unclaimed component {actual_comp}"
        errors.append(
            f"{path}: trace row {assertion.row_index + 1} ({assertion.row_label}) "
            f".c{assertion.col} expected {assertion.net_name}, reaches {actual}"
        )
    if errors:
        raise ValueError("\n".join(errors))


def validate_trace_intents(path: Path, trace: Layer, intents: TraceIntents, max_col: int) -> None:
    assertions = extract_trace_net_assertions(trace, max_col)
    if not intents.nets and not intents.disjoint and not assertions:
        return
    validate_module_leg_short_risk(path, trace, max_col)
    row_index = build_row_label_index(trace)
    components = flood_fill_components(trace, max_col)
    endpoint_components: Dict[str, List[Tuple[CellRef, int]]] = {}
    for net_name, endpoints in intents.nets.items():
        comps: List[Tuple[CellRef, int]] = []
        for ref in endpoints:
            cell = resolve_cell_ref(path, trace, ref, row_index)
            if cell not in components:
                raise ValueError(
                    f"{path}: intent net {net_name!r} endpoint "
                    f"{ref.row_label}:{ref.occurrence}.c{ref.col} is isolated copper"
                )
            comps.append((ref, components[cell]))
        endpoint_components[net_name] = comps
        comp_ids = {comp for _, comp in comps}
        if len(comp_ids) > 1:
            detail = ", ".join(
                f"{ref.row_label}:{ref.occurrence}.c{ref.col}->comp{comp}"
                for ref, comp in comps
            )
            raise ValueError(
                f"{path}: intent net {net_name!r} split across components: {detail}"
            )
    for net_a, net_b in intents.disjoint:
        if net_a not in endpoint_components:
            raise ValueError(f"{path}: disjoint references unknown net {net_a!r}")
        if net_b not in endpoint_components:
            raise ValueError(f"{path}: disjoint references unknown net {net_b!r}")
        comps_a = {comp for _, comp in endpoint_components[net_a]}
        comps_b = {comp for _, comp in endpoint_components[net_b]}
        if comps_a & comps_b:
            raise ValueError(
                f"{path}: disjoint violation: nets {net_a!r} and {net_b!r} share "
                f"copper (components {sorted(comps_a & comps_b)})"
            )
    validate_trace_net_assertions(path, trace, assertions, components, endpoint_components)


def validate_trace_col_assertions(path: Path, trace: Layer, profile: Optional[BoardVoxProfile]) -> None:
    max_col = inner_column_count(trace)
    for row_index, row in enumerate(trace.rows, 1):
        label = row_label(row) or f"row {row_index}"
        assertions = extract_col_assertions(row)
        if not assertions:
            continue
        window = design_window(trace, row)
        for col, token in assertions:
            problem = validate_col_assertion(window, max_col, col, token)
            if problem is not None:
                raise ValueError(
                    f"{path}: trace row {row_index} ({label}) "
                    f"{col_label(col, profile, trace)}={token}: {problem}"
                )


def collect_pad_crowding_warnings(
    path: Path,
    layer_name: str,
    layer: Layer,
    profile: Optional[BoardVoxProfile],
) -> List[str]:
    """Warn when adjacent */O pads may crowd routing on one row."""
    warnings: List[str] = []
    hint = "review crowding for this board profile"
    if profile is not None:
        hint = profile.crowding_hints.get(path.stem, hint)
    for row_index, row in enumerate(layer.rows, 1):
        label = row_label(row) or f"row {row_index}"
        window = design_window(layer, row)
        for col in range(len(window) - 1):
            pair = window[col : col + 2]
            if pair not in {"*O", "O*"}:
                continue
            warnings.append(
                f"warn {path.name}: layer {layer_name!r} {label} "
                f"{col_label(col, profile, layer)}-{col_label(col + 1, profile, layer)}: "
                f"{pair} adjacency ({hint})"
            )
    return warnings


def validate_trace_pads_match_base(
    path: Path,
    base: Layer,
    trace: Layer,
    expectations: Sequence[RowExpectation],
    profile: Optional[BoardVoxProfile],
) -> None:
    by_label: Mapping[str, RowExpectation] = {item.label: item for item in expectations}
    for row_index, (base_row, trace_row) in enumerate(zip(base.rows, trace.rows), 1):
        label = row_label(base_row)
        if label is None or label not in by_label:
            continue
        expect = by_label[label]
        base_window = design_window(base, base_row)
        trace_window = design_window(trace, trace_row)
        for col in expect.pin_cols | expect.o_cols:
            base_char = base_window[col]
            trace_char = trace_window[col]
            if base_char not in PAD_CHARS:
                raise ValueError(
                    f"{path}: internal error: base row {label} "
                    f"{col_label(col, profile, base)} is {base_char!r}, not a pad"
                )
            if trace_char != base_char:
                raise ValueError(
                    f"{path}: trace row {row_index} ({label}) "
                    f"{col_label(col, profile, trace)}: expected {base_char!r}, "
                    f"got {trace_char!r}"
                )


def validate_layer_geometry(path: Path, layers: Mapping[str, Layer]) -> Tuple[Layer, Layer]:
    missing = [layer for layer in REQUIRED_LAYERS if layer not in layers]
    if missing:
        raise ValueError(f"{path}: missing required layers: {', '.join(missing)}")

    base = layers[REQUIRED_LAYERS[0]]
    trace = layers[REQUIRED_LAYERS[1]]
    if base.height == 0 or base.width == 0:
        raise ValueError(f"{path}: base layer is empty")

    for layer_name, layer in layers.items():
        if layer.offset != base.offset or layer.width != base.width:
            raise ValueError(
                f"{path}: layer {layer_name!r} has geometry "
                f"({layer.offset}, {layer.width}); expected ({base.offset}, {base.width})"
            )
        if layer.height != base.height:
            raise ValueError(
                f"{path}: layer {layer_name!r} declares {layer.height} rows; "
                f"expected {base.height}"
            )
        if len(layer.rows) != base.height:
            raise ValueError(
                f"{path}: layer {layer_name!r} has {len(layer.rows)} rows; "
                f"expected {base.height}"
            )
        for row_index, row in enumerate(layer.rows, 1):
            if len(design_window(layer, row)) != base.width:
                raise ValueError(f"{path}: layer {layer_name!r} row {row_index} has bad width")
    return base, trace


def validate(path: Path) -> List[str]:
    layers = read_layers(path)
    base, trace = validate_layer_geometry(path, layers)
    profile = board_profile_for_path(path.resolve())
    max_col = inner_column_count(base)

    if profile is not None and max_col != profile.expected_inner_cols:
        raise ValueError(
            f"{path}: profile {profile.name!r} expects {profile.expected_inner_cols} "
            f"inner columns, got {max_col}"
        )

    pin_layout: Optional[Tuple[RowExpectation, ...]] = None
    if profile is not None:
        pin_layout = profile.row_layouts.get(path.stem)
    if pin_layout is not None:
        validate_pin_layout(path, "base", base, pin_layout, profile)
        validate_pin_layout(path, "trace", trace, pin_layout, profile)
        validate_trace_pads_match_base(path, base, trace, pin_layout, profile)

    validate_trace_col_assertions(path, trace, profile)
    intents = read_trace_intents(path, max_col)
    validate_trace_intents(path, trace, intents, max_col)

    warnings = collect_pad_crowding_warnings(path, "base", base, profile)
    print(f"ok {path.name}: {len(layers)} layers, {base.width} x {base.height}")
    return warnings


def default_vox_paths() -> List[Path]:
    hardware_root = Path(__file__).resolve().parent
    return sorted(hardware_root.glob("*/hat/*.vox"))


def main(argv: Sequence[str]) -> int:
    paths = [Path(arg) for arg in argv[1:]]
    if not paths:
        paths = default_vox_paths()
    errors: List[str] = []
    for path in paths:
        try:
            for message in validate(path):
                print(message, file=sys.stderr)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(str(exc))
    if errors:
        for error in errors:
            print(f"error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
