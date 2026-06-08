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
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Set, Tuple

ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzX*O.-|+/\\?T^v<> +-")
ALLOWED_CHARS.update("┌┐└┘├┤┬┴┼─│")
REQUIRED_LAYERS = ("base", "trace")
LAYER_HEADER_RE = re.compile(r"^layer\s+([A-Za-z0-9_-]+)\s+\((\d+),\s*(\d+),\s*(\d+)\)$")
ROW_LABEL_RE = re.compile(r"^\s*(\S+)")
TRACE_COL_ASSERT_RE = re.compile(r"c(\d+)=(-\*|\*-|\||\+|-|[┌┐└┘├┤┬┴┼─│])")
INTENT_NET_RE = re.compile(r"^#\s*net\s+(\S+)\s+(.+)$")
INTENT_DISJOINT_RE = re.compile(r"^#\s*disjoint\s+(.+)$")
INTENT_ENDPOINT_RE = re.compile(r"^([A-Za-z0-9_:-]+)\.c(\d+)$")

PIN_PAD_CHAR = "*"
LEG_PAD_CHAR = "O"
BOX_CHARS: FrozenSet[str] = frozenset({"┌", "┐", "└", "┘", "├", "┤", "┬", "┴", "┼", "─", "│"})
COPPER_CHARS: FrozenSet[str] = frozenset({PIN_PAD_CHAR, LEG_PAD_CHAR, "-", "|", "+"}) | BOX_CHARS
PAD_CHARS: FrozenSet[str] = frozenset({PIN_PAD_CHAR, LEG_PAD_CHAR})
ARMS_BY_CHAR: Mapping[str, FrozenSet[str]] = {
    PIN_PAD_CHAR: frozenset({"N", "E", "S", "W"}),
    LEG_PAD_CHAR: frozenset({"N", "E", "S", "W"}),
    "-": frozenset({"E", "W"}),
    "|": frozenset({"N", "S"}),
    "+": frozenset({"N", "E", "S", "W"}),
    "┌": frozenset({"E", "S"}),
    "┐": frozenset({"S", "W"}),
    "└": frozenset({"N", "E"}),
    "┘": frozenset({"N", "W"}),
    "├": frozenset({"N", "E", "S"}),
    "┤": frozenset({"N", "S", "W"}),
    "┬": frozenset({"E", "S", "W"}),
    "┴": frozenset({"N", "E", "W"}),
    "┼": frozenset({"N", "E", "S", "W"}),
    "─": frozenset({"E", "W"}),
    "│": frozenset({"N", "S"}),
}

# Horizontal no-connect pairs (SKILL.md).
H_NO_CONNECT: FrozenSet[Tuple[str, str]] = frozenset(
    {
        (PIN_PAD_CHAR, PIN_PAD_CHAR),
        (LEG_PAD_CHAR, LEG_PAD_CHAR),
        (PIN_PAD_CHAR, LEG_PAD_CHAR),
        (LEG_PAD_CHAR, PIN_PAD_CHAR),
        (PIN_PAD_CHAR, "|"),
        ("|", PIN_PAD_CHAR),
        (LEG_PAD_CHAR, "|"),
        ("|", LEG_PAD_CHAR),
        ("|", "|"),
        ("-", "|"),
        ("|", "-"),
        ("+", "|"),
        ("|", "+"),
    }
)

# Vertical no-connect pairs (SKILL.md).
V_NO_CONNECT: FrozenSet[Tuple[str, str]] = frozenset(
    {
        (PIN_PAD_CHAR, PIN_PAD_CHAR),
        (LEG_PAD_CHAR, LEG_PAD_CHAR),
        (PIN_PAD_CHAR, LEG_PAD_CHAR),
        (LEG_PAD_CHAR, PIN_PAD_CHAR),
        ("-", "-"),
        ("-", "|"),
        ("|", "-"),
        ("-", "+"),
        ("+", "-"),
        ("-", PIN_PAD_CHAR),
        (PIN_PAD_CHAR, "-"),
        ("-", LEG_PAD_CHAR),
        (LEG_PAD_CHAR, "-"),
    }
)

# Design-window column indices 1..8 map to grid columns c1..c8.
COL_LABELS: Dict[int, str] = {
    1: "c1",
    2: "c2",
    3: "c3",
    4: "c4",
    5: "c5",
    6: "c6",
    7: "c7",
    8: "c8",
}

X_MM_BY_COL: Dict[int, float] = {
    1: -8.89,
    2: -6.35,
    3: -3.81,
    4: -1.27,
    5: 1.27,
    6: 3.81,
    7: 6.35,
    8: 8.89,
}


@dataclass(frozen=True)
class Layer:
    name: str
    offset: int
    width: int
    height: int
    rows: List[str]


@dataclass(frozen=True)
class RowExpectation:
    """Expected */O pad columns for one labeled row (design-window indices 1..8)."""

    label: str
    pin_cols: FrozenSet[int]
    O_cols: FrozenSet[int]


# West Pico *@c1 and east Pico *@c8 on every labeled header row.
_HEADER_PINS: FrozenSet[int] = frozenset({1, 8})


def _row(label: str, pin_cols: FrozenSet[int], O_cols: FrozenSet[int]) -> RowExpectation:
    return RowExpectation(label=label, pin_cols=pin_cols, O_cols=O_cols)


UP_SIDE_PIN_LAYOUT: Tuple[RowExpectation, ...] = (
    _row("GP15", _HEADER_PINS, frozenset()),
    _row("GP14", _HEADER_PINS, frozenset()),
    _row("GND", _HEADER_PINS, frozenset()),
    _row("GP13", _HEADER_PINS, frozenset({4, 5, 6})),  # IR RX OUT GND VCC
    _row("GP12", _HEADER_PINS, frozenset()),
    _row("GP11", _HEADER_PINS, frozenset()),
    _row("GP10", _HEADER_PINS, frozenset({4, 5, 6})),  # IR TX DAT GND VCC
    _row("GP9", _HEADER_PINS, frozenset()),
    _row("GP8", _HEADER_PINS, frozenset()),
    _row("GP7", _HEADER_PINS, frozenset()),
    _row("GP6", _HEADER_PINS, frozenset()),
    _row("GP5", _HEADER_PINS, frozenset()),
    _row("GP4", _HEADER_PINS, frozenset({3, 4, 5, 6})),  # AHT20 SDA SCL GND 3V3
    _row("GP3", _HEADER_PINS, frozenset()),
    _row("GP2", _HEADER_PINS, frozenset()),
    _row("GP1", _HEADER_PINS, frozenset()),
    _row("GP0", _HEADER_PINS, frozenset()),
)

PICO_SIDE_PIN_LAYOUT: Tuple[RowExpectation, ...] = (
    _row("P20", _HEADER_PINS, frozenset()),
    _row("P19", _HEADER_PINS, frozenset()),
    _row("P18", _HEADER_PINS, frozenset()),
    _row("P17", _HEADER_PINS, frozenset({3, 4, 5})),  # IR RX mirrored
    _row("P16", _HEADER_PINS, frozenset()),
    _row("P15", _HEADER_PINS, frozenset()),
    _row("P14", _HEADER_PINS, frozenset({3, 4, 5})),  # IR TX mirrored
    _row("P13", _HEADER_PINS, frozenset()),
    _row("P12", _HEADER_PINS, frozenset()),
    _row("P11", _HEADER_PINS, frozenset()),
    _row("P10", _HEADER_PINS, frozenset()),
    _row("P9", _HEADER_PINS, frozenset()),
    _row("P8", _HEADER_PINS, frozenset()),
    _row("P7", _HEADER_PINS, frozenset()),
    _row("P6", _HEADER_PINS, frozenset({3, 4, 5, 6})),  # AHT20 mirrored
    _row("P5", _HEADER_PINS, frozenset()),
    _row("P4", _HEADER_PINS, frozenset()),
    _row("P3", _HEADER_PINS, frozenset()),
    _row("P2", _HEADER_PINS, frozenset()),
    _row("P1", _HEADER_PINS, frozenset()),
)

VARIANT_PIN_LAYOUTS: Dict[str, Tuple[RowExpectation, ...]] = {
    "up-side": UP_SIDE_PIN_LAYOUT,
    "pico-side": PICO_SIDE_PIN_LAYOUT,
}


@dataclass(frozen=True)
class CellRef:
    """Trace grid cell: row label, 1-based duplicate index, column 1..8."""

    row_label: str
    occurrence: int
    col: int


@dataclass
class TraceIntents:
    nets: Dict[str, List[CellRef]] = field(default_factory=dict)
    disjoint: List[Tuple[str, str]] = field(default_factory=list)


def read_layers(path: Path) -> Dict[str, Layer]:
    layers: Dict[str, Layer] = {}
    current: Layer | None = None
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


def col_label(col_index: int) -> str:
    name = COL_LABELS.get(col_index, f"i{col_index}")
    x_mm = X_MM_BY_COL.get(col_index)
    if x_mm is None:
        return name
    return f"{name} (x={x_mm})"


def find_pad_columns(window: str) -> Tuple[FrozenSet[int], FrozenSet[int]]:
    pin_cols: set[int] = set()
    O_cols: set[int] = set()
    for index, char in enumerate(window):
        if char == PIN_PAD_CHAR:
            pin_cols.add(index)
        elif char == LEG_PAD_CHAR:
            O_cols.add(index)
    return frozenset(pin_cols), frozenset(O_cols)


def validate_pin_layout(
    path: Path,
    layer_name: str,
    layer: Layer,
    expectations: Sequence[RowExpectation],
) -> None:
    by_label: Dict[str, RowExpectation] = {item.label: item for item in expectations}
    seen: set[str] = set()
    for row_index, row in enumerate(layer.rows, 1):
        label = row_label(row)
        if label is None:
            continue
        if label not in by_label:
            continue
        seen.add(label)
        expect = by_label[label]
        window = design_window(layer, row)
        pin_cols, O_cols = find_pad_columns(window)
        expected_pin = expect.pin_cols
        expected_O = expect.O_cols
        if pin_cols != expected_pin:
            raise ValueError(
                f"{path}: layer {layer_name!r} row {row_index} ({label}): "
                f"{PIN_PAD_CHAR} columns {sorted(pin_cols)} != expected {sorted(expected_pin)} "
                f"({', '.join(col_label(c) for c in sorted(expected_pin))})"
            )
        if O_cols != expected_O:
            raise ValueError(
                f"{path}: layer {layer_name!r} row {row_index} ({label}): "
                f"O columns {sorted(O_cols)} != expected {sorted(expected_O)} "
                f"({', '.join(col_label(c) for c in sorted(expected_O))})"
            )
        allowed_pad_cols = expected_pin | expected_O
        extras = (pin_cols | O_cols) - allowed_pad_cols
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


def validate_col_assertion(window: str, col: int, token: str) -> Optional[str]:
    if col < 1 or col > 8:
        return f"column {col} out of design range 1..8"
    if token in {"|", "+", "-"} | BOX_CHARS:
        actual = window[col]
        if actual != token:
            return f"expected {token!r}, got {actual!r}"
        return None
    if token == "*-":
        if col >= 8:
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


def parse_intent_endpoint(token: str) -> CellRef:
    match = INTENT_ENDPOINT_RE.match(token.strip())
    if match is None:
        raise ValueError(f"invalid intent endpoint {token!r} (want LABEL.cN or LABEL:N.cN)")
    label_token = match.group(1)
    col = int(match.group(2))
    if col < 1 or col > 8:
        raise ValueError(f"intent endpoint {token!r}: column must be 1..8")
    occurrence = 1
    row_label = label_token
    if ":" in label_token:
        base, _, index_text = label_token.partition(":")
        if not index_text.isdigit():
            raise ValueError(f"intent endpoint {token!r}: row occurrence must be digits after ':'")
        occurrence = int(index_text)
        row_label = base
    return CellRef(row_label=row_label, occurrence=occurrence, col=col)


def read_trace_intents(path: Path) -> TraceIntents:
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
                endpoints = [parse_intent_endpoint(token) for token in tokens]
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
            continue
    return intents


def build_row_label_index(trace: Layer) -> Dict[Tuple[str, int], int]:
    """Map (row_label, 1-based occurrence) -> trace row index."""
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


def flood_fill_components(trace: Layer) -> Dict[Tuple[int, int], int]:
    """Return (row_index, col) -> component id for all copper cells."""
    components: Dict[Tuple[int, int], int] = {}
    next_id = 0
    height = len(trace.rows)
    for row_i in range(height):
        for col in range(1, 9):
            if (row_i, col) in components:
                continue
            char = trace_char_at(trace, row_i, col)
            if char not in COPPER_CHARS:
                continue
            queue: deque[Tuple[int, int]] = deque([(row_i, col)])
            components[(row_i, col)] = next_id
            while queue:
                r, c = queue.popleft()
                here = trace_char_at(trace, r, c)
                if c > 1:
                    left = trace_char_at(trace, r, c - 1)
                    if (r, c - 1) not in components and horizontal_connects(left, here):
                        components[(r, c - 1)] = next_id
                        queue.append((r, c - 1))
                if c < 8:
                    right = trace_char_at(trace, r, c + 1)
                    if (r, c + 1) not in components and horizontal_connects(here, right):
                        components[(r, c + 1)] = next_id
                        queue.append((r, c + 1))
                if r > 0:
                    up = trace_char_at(trace, r - 1, c)
                    if (r - 1, c) not in components and vertical_connects(up, here):
                        components[(r - 1, c)] = next_id
                        queue.append((r - 1, c))
                if r + 1 < height:
                    down = trace_char_at(trace, r + 1, c)
                    if (r + 1, c) not in components and vertical_connects(here, down):
                        components[(r + 1, c)] = next_id
                        queue.append((r + 1, c))
            next_id += 1
    return components


def validate_module_leg_short_risk(path: Path, trace: Layer) -> None:
    """Fail when a bridge actually contacts both module O legs below it."""
    for row_i in range(len(trace.rows) - 1):
        upper_label = row_label(trace.rows[row_i]) or f"row {row_i + 1}"
        upper = design_window(trace, trace.rows[row_i])
        lower = design_window(trace, trace.rows[row_i + 1])
        for col in range(1, 8):
            left = upper[col]
            right = upper[col + 1]
            if left not in COPPER_CHARS or right not in COPPER_CHARS:
                continue
            if not horizontal_connects(left, right):
                continue
            if (
                lower[col] == "O"
                and lower[col + 1] == "O"
                and vertical_connects(left, lower[col])
                and vertical_connects(right, lower[col + 1])
            ):
                raise ValueError(
                    f"{path}: trace row {row_i + 1} ({upper_label}) "
                    f"{col_label(col)}-{col_label(col + 1)} bridge contacts both "
                    f"module O legs on row below"
                )


def validate_trace_intents(path: Path, trace: Layer, intents: TraceIntents) -> None:
    if not intents.nets and not intents.disjoint:
        return
    validate_module_leg_short_risk(path, trace)
    row_index = build_row_label_index(trace)
    components = flood_fill_components(trace)
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


def validate_trace_col_assertions(path: Path, trace: Layer) -> None:
    for row_index, row in enumerate(trace.rows, 1):
        label = row_label(row) or f"row {row_index}"
        assertions = extract_col_assertions(row)
        if not assertions:
            continue
        window = design_window(trace, row)
        for col, token in assertions:
            problem = validate_col_assertion(window, col, token)
            if problem is not None:
                raise ValueError(
                    f"{path}: trace row {row_index} ({label}) {col_label(col)}={token}: {problem}"
                )


def collect_pad_crowding_warnings(
    path: Path,
    layer_name: str,
    layer: Layer,
) -> List[str]:
    """Warn when adjacent */O pads may crowd routing (*O or O* on one row)."""
    warnings: List[str] = []
    for row_index, row in enumerate(layer.rows, 1):
        label = row_label(row) or f"row {row_index}"
        window = design_window(layer, row)
        for col in range(len(window) - 1):
            pair = window[col : col + 2]
            if pair not in {"*O", "O*"}:
                continue
            hint = (
                "on up-side: shift module legs and center rails one column east"
                if path.stem == "up-side"
                else "pico-side layout is separate; review crowding on its own terms"
            )
            warnings.append(
                f"warn {path.name}: layer {layer_name!r} {label} "
                f"{col_label(col)}-{col_label(col + 1)}: {pair} adjacency ({hint})"
            )
    return warnings


def validate_trace_pads_match_base(
    path: Path,
    base: Layer,
    trace: Layer,
    expectations: Sequence[RowExpectation],
) -> None:
    by_label: Mapping[str, RowExpectation] = {item.label: item for item in expectations}
    for row_index, (base_row, trace_row) in enumerate(zip(base.rows, trace.rows), 1):
        label = row_label(base_row)
        if label is None or label not in by_label:
            continue
        expect = by_label[label]
        pad_cols = expect.pin_cols | expect.O_cols
        base_window = design_window(base, base_row)
        trace_window = design_window(trace, trace_row)
        for col in pad_cols:
            base_char = base_window[col]
            trace_char = trace_window[col]
            if base_char not in PAD_CHARS:
                raise ValueError(
                    f"{path}: internal error: base row {label} col {col_label(col)} "
                    f"is {base_char!r}, not a pad"
                )
            if trace_char != base_char:
                raise ValueError(
                    f"{path}: trace row {row_index} ({label}) {col_label(col)}: "
                    f"expected {base_char!r}, got {trace_char!r}"
                )


def validate(path: Path) -> List[str]:
    layers = read_layers(path)
    missing = [layer for layer in REQUIRED_LAYERS if layer not in layers]
    if missing:
        raise ValueError(f"{path}: missing required layers: {', '.join(missing)}")

    base = layers[REQUIRED_LAYERS[0]]
    trace = layers[REQUIRED_LAYERS[1]]
    expected_height = base.height
    expected_width = base.width
    expected_offset = base.offset
    if expected_height == 0 or expected_width == 0:
        raise ValueError(f"{path}: base layer is empty")

    for layer_name, layer in layers.items():
        if layer.offset != expected_offset or layer.width != expected_width:
            raise ValueError(
                f"{path}: layer {layer_name!r} has geometry "
                f"({layer.offset}, {layer.width}); expected ({expected_offset}, {expected_width})"
            )
        if layer.height != expected_height:
            raise ValueError(
                f"{path}: layer {layer_name!r} declares {layer.height} rows; expected {expected_height}"
            )
        if len(layer.rows) != expected_height:
            raise ValueError(
                f"{path}: layer {layer_name!r} has {len(layer.rows)} rows; expected {expected_height}"
            )
        for row_index, row in enumerate(layer.rows, 1):
            if len(design_window(layer, row)) != expected_width:
                raise ValueError(f"{path}: layer {layer_name!r} row {row_index} has bad width")

    pin_layout = VARIANT_PIN_LAYOUTS.get(path.stem)
    if pin_layout is not None:
        validate_pin_layout(path, "base", base, pin_layout)
        validate_pin_layout(path, "trace", trace, pin_layout)
        validate_trace_pads_match_base(path, base, trace, pin_layout)

    validate_trace_col_assertions(path, trace)

    intents = read_trace_intents(path)
    validate_trace_intents(path, trace, intents)

    warnings = collect_pad_crowding_warnings(path, "base", base)
    print(f"ok {path.name}: {len(layers)} layers, {expected_width} x {expected_height}")
    return warnings


def main(argv: List[str]) -> int:
    paths = [Path(arg) for arg in argv[1:]]
    if not paths:
        paths = sorted(Path(__file__).resolve().parent.glob("*.vox"))
    try:
        for path in paths:
            for message in validate(path):
                print(message, file=sys.stderr)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
