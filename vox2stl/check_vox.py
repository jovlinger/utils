#!/usr/bin/env python3
"""Validate HAT text voxel design files.

VOX files are treated as human-readable binary design artifacts and may use
UTF-8 box-drawing glyphs in the checked diagram window.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, FrozenSet, List, Mapping, Optional, Sequence, Tuple

from constants import (
    VoxAlias,
    correct_vox_shorthand_text,
    effective_trace_char,
    parse_alias_line,
    parse_layer_header,
    parse_vox_aliases_text,
    trace_arms,
)

PIN_PAD_CHAR = "*"
LEG_PAD_CHAR = "O"

BOX_UL = "\u250c"
BOX_UR = "\u2510"
BOX_LL = "\u2514"
BOX_LR = "\u2518"
BOX_T_RIGHT = "\u251c"
BOX_T_LEFT = "\u2524"
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
    BOX_T_RIGHT: frozenset({"N", "E", "S"}),
    BOX_T_LEFT: frozenset({"N", "S", "W"}),
    BOX_T_DOWN: frozenset({"E", "S", "W"}),
    BOX_T_UP: frozenset({"N", "E", "W"}),
    BOX_CROSS: frozenset({"N", "E", "S", "W"}),
    BOX_H: frozenset({"E", "W"}),
    BOX_V: frozenset({"N", "S"}),
}

ALLOWED_CHARS = set("abcdefghijklmnopqrstuvwxyzX*O.-|+/\\?T^v<> +-")
ALLOWED_CHARS.update(BOX_CHARS)
TRACE_LAYER_NAME = "trace"
ROW_LABEL_RE = re.compile(r"^\s*(\S+)")
BOX_ASSERT_CHARS = "".join(re.escape(char) for char in sorted(BOX_CHARS))
TRACE_COL_ASSERT_RE = re.compile(r"c(\d+)=(-\*|\*-|\||\+|-|[" + BOX_ASSERT_CHARS + r"])")
TRACE_NET_ASSERT_RE = re.compile(r"\.c(\d+)\s*=\s*([A-Za-z0-9_:-]+)")
NET_ALIAS_RE = re.compile(r"^net\s+alias\s+([A-Za-z0-9_:-]+)\s*=\s*([A-Za-z0-9_:-]+)$")
INTENT_NET_RE = re.compile(r"^#\s*net\s+(\S+)\s+(.+)$")
INTENT_DISJOINT_RE = re.compile(r"^#\s*disjoint\s+(.+)$")
INTENT_ENDPOINT_RE = re.compile(r"^([A-Za-z0-9_:-]+)\.c(\d+)$")
DEFAULT_NET_ALIASES: Dict[str, str] = {"VCC": "3V3"}


def is_copper_char(char: str, aliases: Mapping[str, VoxAlias]) -> bool:
    return effective_trace_char(char, aliases) in COPPER_CHARS


def is_pad_char(char: str, aliases: Mapping[str, VoxAlias]) -> bool:
    return effective_trace_char(char, aliases) in PAD_CHARS


def parse_net_alias_line(line: str) -> Optional[Tuple[str, str]]:
    match = NET_ALIAS_RE.match(line)
    if match is None:
        return None
    return match.group(1), match.group(2)


def parse_net_aliases_text(text: str) -> Dict[str, str]:
    net_aliases: Dict[str, str] = dict(DEFAULT_NET_ALIASES)
    for raw_line in text.splitlines():
        alias = parse_net_alias_line(raw_line.strip())
        if alias is not None:
            source, target = alias
            net_aliases[source] = target
    return net_aliases


def canonical_net_name(net_name: str, net_aliases: Mapping[str, str]) -> str:
    seen = {net_name}
    current = net_name
    while current in net_aliases:
        next_name = net_aliases[current]
        if next_name in seen:
            return current
        seen.add(next_name)
        current = next_name
    return current


@dataclass(frozen=True)
class Layer:
    name: str
    offset: int
    width: int
    height: int
    layer_thickness_mm: float
    rows: List[str]


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


class ValidationError(ValueError):
    def __init__(self, errors: Sequence[str], warnings: Sequence[str]) -> None:
        super().__init__("\n".join(errors))
        self.errors: List[str] = list(errors)
        self.warnings: List[str] = list(warnings)


def inner_column_count(layer: Layer) -> int:
    return max(0, layer.width - 2)


def col_label(col_index: int, layer: Optional[Layer] = None) -> str:
    name = f"c{col_index}"
    if layer is None:
        return name
    inner_cols = inner_column_count(layer)
    center = (inner_cols + 1) * 0.5
    x_mm = (col_index - center) * 2.54
    return f"{name} (x={x_mm:.2f})"


def checked_window(layer: Layer, row: str) -> str:
    start = max(layer.offset - 1, 0)
    end = layer.offset + layer.width + 1
    return row.ljust(end)[start:end]


def design_window(layer: Layer, row: str) -> str:
    end = layer.offset + layer.width
    return row.ljust(end)[layer.offset:end]


def row_label(row: str, layer: Optional[Layer] = None) -> Optional[str]:
    text = row if layer is None else row[: layer.offset]
    match = ROW_LABEL_RE.match(text)
    if match is None:
        return None
    token = match.group(1)
    if token.startswith("X") or token == ".":
        return None
    return token


def right_row_label(row: str, layer: Layer) -> Optional[str]:
    text = row[layer.offset + layer.width :]
    match = ROW_LABEL_RE.match(text)
    if match is None:
        return None
    token = match.group(1)
    if token.startswith("X") or token == ".":
        return None
    return token


def read_layers(path: Path) -> Dict[str, Layer]:
    text = path.read_text(encoding="utf-8")
    aliases = parse_vox_aliases_text(text)
    allowed_chars = ALLOWED_CHARS | set(aliases)
    layers: Dict[str, Layer] = {}
    current: Optional[Layer] = None
    for line_no, raw_line in enumerate(text.splitlines(), 1):
        line = raw_line.rstrip("\n")
        if not line or line.startswith("#"):
            continue
        stripped = line.strip()
        if parse_alias_line(stripped) is not None or parse_net_alias_line(stripped) is not None:
            continue
        header = parse_layer_header(line)
        if header is not None:
            name = header.name
            if name in layers:
                raise ValueError(f"{path}:{line_no}: duplicate layer {name!r}")
            current = Layer(
                name=name,
                offset=header.offset,
                width=header.width,
                height=header.height,
                layer_thickness_mm=header.layer_thickness_mm,
                rows=[],
            )
            layers[name] = current
            continue
        if line.startswith("layer "):
            raise ValueError(f"{path}:{line_no}: invalid layer header")
        if current is None:
            raise ValueError(f"{path}:{line_no}: content before first layer")
        window = checked_window(current, line)
        bad_chars = sorted(set(window) - allowed_chars)
        if bad_chars:
            raise ValueError(
                f"{path}:{line_no}: invalid chars in checked window {''.join(bad_chars)!r}"
            )
        current.rows.append(line)
    return layers


def correct_vox_file(path: Path) -> bool:
    text = path.read_text(encoding="utf-8")
    corrected = correct_vox_shorthand_text(text)
    if corrected == text:
        return False
    path.write_text(corrected, encoding="utf-8")
    return True


def extract_col_assertions(row: str) -> List[Tuple[int, str]]:
    return [(int(match.group(1)), match.group(2)) for match in TRACE_COL_ASSERT_RE.finditer(row)]


def extract_trace_net_assertions(
    trace: Layer,
    max_col: int,
    aliases: Mapping[str, VoxAlias],
    net_aliases: Mapping[str, str],
) -> Tuple[List[TraceNetAssertion], List[str]]:
    assertions: List[TraceNetAssertion] = []
    errors: List[str] = []
    for row_i, row in enumerate(trace.rows):
        label = row_label(row, trace) or f"row {row_i + 1}"
        for match in TRACE_NET_ASSERT_RE.finditer(row):
            col = int(match.group(1))
            if col < 1 or col > max_col:
                errors.append(
                    f"trace row {row_i + 1} ({label}) .c{col}: "
                    f"column must be 1..{max_col}"
                )
                continue
            assertions.append(
                TraceNetAssertion(
                    row_index=row_i,
                    row_label=label,
                    col=col,
                    net_name=canonical_net_name(match.group(2), net_aliases),
                )
            )
        window = design_window(trace, row)
        for col in range(1, max_col + 1):
            alias = aliases.get(window[col])
            if alias is not None:
                assertions.append(
                    TraceNetAssertion(
                        row_index=row_i,
                        row_label=label,
                        col=col,
                        net_name=canonical_net_name(alias.net_name, net_aliases),
                    )
                )
    return assertions, errors


def validate_col_assertion(
    window: str,
    max_col: int,
    col: int,
    token: str,
    aliases: Mapping[str, VoxAlias],
) -> Optional[str]:
    if col < 1 or col > max_col:
        return f"column {col} out of design range 1..{max_col}"
    if token in {"|", "+", "-"} | BOX_CHARS:
        actual = window[col]
        if effective_trace_char(actual, aliases) != token:
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


def read_trace_intents(
    path: Path,
    max_col: int,
    net_aliases: Mapping[str, str],
) -> TraceIntents:
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
            name = canonical_net_name(net_match.group(1), net_aliases)
            tokens = net_match.group(2).split()
            try:
                endpoints = [parse_intent_endpoint(token, max_col) for token in tokens]
            except ValueError:
                continue
            intents.nets[name] = endpoints
            continue
        disjoint_match = INTENT_DISJOINT_RE.match(line)
        if disjoint_match:
            names = [
                canonical_net_name(name, net_aliases)
                for name in disjoint_match.group(1).split()
            ]
            if len(names) != 2:
                raise ValueError(f"disjoint expects two net names, got {names!r}")
            intents.disjoint.append((names[0], names[1]))
    return intents


def build_row_label_index(trace: Layer) -> Dict[Tuple[str, int], int]:
    """Map (row_label, 1-based occurrence) to trace row index."""
    seen: Dict[str, int] = {}
    index: Dict[Tuple[str, int], int] = {}
    for row_index, row in enumerate(trace.rows):
        label = row_label(row, trace)
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
    aliases: Mapping[str, VoxAlias],
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
    if not is_copper_char(char, aliases):
        raise ValueError(
            f"{path}: intent endpoint {ref.row_label}:{ref.occurrence}.c{ref.col} "
            f"is {char!r}, not copper"
        )
    return row_i, ref.col


def horizontal_connects(left: str, right: str, aliases: Mapping[str, VoxAlias]) -> bool:
    if is_pad_char(left, aliases) and is_pad_char(right, aliases):
        return False
    effective_left = effective_trace_char(left, aliases)
    effective_right = effective_trace_char(right, aliases)
    if (effective_left, effective_right) in {
        (BOX_T_RIGHT, "-"),
        ("-", BOX_T_LEFT),
    }:
        return True
    if (effective_left, effective_right) in {
        ("-", BOX_T_RIGHT),
        (BOX_T_LEFT, "-"),
    }:
        return False
    return "E" in trace_arms(left, aliases) and "W" in trace_arms(right, aliases)


def vertical_connects(top: str, bottom: str, aliases: Mapping[str, VoxAlias]) -> bool:
    if is_pad_char(top, aliases) and is_pad_char(bottom, aliases):
        return False
    return "S" in trace_arms(top, aliases) and "N" in trace_arms(bottom, aliases)


def trace_char_at(trace: Layer, row_i: int, col: int) -> str:
    return design_window(trace, trace.rows[row_i])[col]


def flood_fill_components(
    trace: Layer,
    max_col: int,
    aliases: Mapping[str, VoxAlias],
) -> Dict[Tuple[int, int], int]:
    """Return (row_index, col) to component id for all copper cells."""
    components: Dict[Tuple[int, int], int] = {}
    next_id = 0
    height = len(trace.rows)
    for row_i in range(height):
        for col in range(1, max_col + 1):
            if (row_i, col) in components:
                continue
            char = trace_char_at(trace, row_i, col)
            if not is_copper_char(char, aliases):
                continue
            queue: deque[Tuple[int, int]] = deque([(row_i, col)])
            components[(row_i, col)] = next_id
            while queue:
                row, current_col = queue.popleft()
                here = trace_char_at(trace, row, current_col)
                if current_col > 1:
                    left = trace_char_at(trace, row, current_col - 1)
                    if (row, current_col - 1) not in components and horizontal_connects(
                        left,
                        here,
                        aliases,
                    ):
                        components[(row, current_col - 1)] = next_id
                        queue.append((row, current_col - 1))
                if current_col < max_col:
                    right = trace_char_at(trace, row, current_col + 1)
                    if (row, current_col + 1) not in components and horizontal_connects(
                        here,
                        right,
                        aliases,
                    ):
                        components[(row, current_col + 1)] = next_id
                        queue.append((row, current_col + 1))
                if row > 0:
                    up = trace_char_at(trace, row - 1, current_col)
                    if (row - 1, current_col) not in components and vertical_connects(
                        up,
                        here,
                        aliases,
                    ):
                        components[(row - 1, current_col)] = next_id
                        queue.append((row - 1, current_col))
                if row + 1 < height:
                    down = trace_char_at(trace, row + 1, current_col)
                    if (row + 1, current_col) not in components and vertical_connects(
                        here,
                        down,
                        aliases,
                    ):
                        components[(row + 1, current_col)] = next_id
                        queue.append((row + 1, current_col))
            next_id += 1
    return components


def validate_module_leg_short_risk(
    path: Path,
    trace: Layer,
    max_col: int,
    aliases: Mapping[str, VoxAlias],
) -> List[str]:
    """Fail when a bridge actually contacts both module O legs below it."""
    errors: List[str] = []
    for row_i in range(len(trace.rows) - 1):
        upper_label = row_label(trace.rows[row_i], trace) or f"row {row_i + 1}"
        upper = design_window(trace, trace.rows[row_i])
        lower = design_window(trace, trace.rows[row_i + 1])
        for col in range(1, max_col):
            left = upper[col]
            right = upper[col + 1]
            if not is_copper_char(left, aliases) or not is_copper_char(right, aliases):
                continue
            if not horizontal_connects(left, right, aliases):
                continue
            if (
                lower[col] == LEG_PAD_CHAR
                and lower[col + 1] == LEG_PAD_CHAR
                and vertical_connects(left, lower[col], aliases)
                and vertical_connects(right, lower[col + 1], aliases)
            ):
                errors.append(
                    f"{path}: trace row {row_i + 1} ({upper_label}) "
                    f"c{col}-c{col + 1} bridge contacts both module O legs on row below"
                )
    return errors


def validate_trace_net_assertions(
    path: Path,
    trace: Layer,
    assertions: Sequence[TraceNetAssertion],
    components: Mapping[Tuple[int, int], int],
    endpoint_components: Mapping[str, Sequence[Tuple[CellRef, int]]],
    aliases: Mapping[str, VoxAlias],
) -> List[str]:
    if not assertions:
        return []
    errors: List[str] = []
    component_nets: Dict[int, List[str]] = {}
    for net_name, refs in endpoint_components.items():
        for _, comp in refs:
            component_nets.setdefault(comp, []).append(net_name)
    for assertion in assertions:
        cell = (assertion.row_index, assertion.col)
        char = trace_char_at(trace, assertion.row_index, assertion.col)
        if not is_copper_char(char, aliases):
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
        if assertion.net_name not in endpoint_components:
            errors.append(
                f"{path}: trace row {assertion.row_index + 1} ({assertion.row_label}) "
                f".c{assertion.col}={assertion.net_name}: unknown net"
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
    return errors


def collect_pin_anchor_components(
    trace: Layer,
    max_col: int,
    components: Mapping[Tuple[int, int], int],
    assertions: Sequence[TraceNetAssertion],
    aliases: Mapping[str, VoxAlias],
    net_aliases: Mapping[str, str],
) -> Dict[str, List[Tuple[CellRef, int]]]:
    anchors: Dict[str, List[Tuple[CellRef, int]]] = {}
    occurrences: Dict[str, int] = {}
    if max_col < 1:
        return anchors
    for row_i, row in enumerate(trace.rows):
        window = design_window(trace, row)
        left_label = row_label(row, trace)
        if left_label is not None and window[1] == PIN_PAD_CHAR:
            net_name = canonical_net_name(left_label, net_aliases)
            cell = (row_i, 1)
            if cell in components:
                occurrences[left_label] = occurrences.get(left_label, 0) + 1
                anchors.setdefault(net_name, []).append(
                    (
                        CellRef(left_label, occurrences[left_label], 1),
                        components[cell],
                    )
                )
        right_label = right_row_label(row, trace)
        if right_label is not None and window[max_col] == PIN_PAD_CHAR:
            net_name = canonical_net_name(right_label, net_aliases)
            cell = (row_i, max_col)
            if cell in components:
                occurrences[right_label] = occurrences.get(right_label, 0) + 1
                anchors.setdefault(net_name, []).append(
                    (
                        CellRef(right_label, occurrences[right_label], max_col),
                        components[cell],
                    )
                )
    return anchors


def validate_component_net_labels(
    path: Path,
    trace: Layer,
    assertions: Sequence[TraceNetAssertion],
    components: Mapping[Tuple[int, int], int],
    pin_components: Mapping[str, Sequence[Tuple[CellRef, int]]],
    aliases: Mapping[str, VoxAlias],
) -> List[str]:
    errors: List[str] = []
    component_labels: Dict[int, Dict[str, List[str]]] = {}
    component_pin_labels: Dict[int, Dict[str, List[str]]] = {}
    def format_ref(ref: CellRef) -> str:
        if ref.occurrence <= 0:
            return f"{ref.row_label}.c{ref.col}"
        return f"{ref.row_label}:{ref.occurrence}.c{ref.col}"

    for net_name, refs in pin_components.items():
        for ref, comp in refs:
            source = format_ref(ref)
            component_labels.setdefault(comp, {}).setdefault(net_name, []).append(source)
            component_pin_labels.setdefault(comp, {}).setdefault(net_name, []).append(source)
    for assertion in assertions:
        cell = (assertion.row_index, assertion.col)
        char = trace_char_at(trace, assertion.row_index, assertion.col)
        if not is_copper_char(char, aliases) or cell not in components:
            continue
        actual_comp = components[cell]
        source = f"{assertion.row_label}.c{assertion.col}"
        component_labels.setdefault(actual_comp, {}).setdefault(assertion.net_name, []).append(source)
    for label_sources in component_labels.values():
        if len(label_sources) <= 1:
            continue
        detail = ", ".join(
            f"{label} from {', '.join(sources)}" for label, sources in sorted(label_sources.items())
        )
        errors.append(
            f"{path}: copper component has conflicting net labels: {detail}"
        )
    for comp, label_sources in component_labels.items():
        if len(label_sources) != 1:
            continue
        net_name, sources = next(iter(label_sources.items()))
        pin_sources = component_pin_labels.get(comp, {}).get(net_name)
        if pin_sources:
            continue
        errors.append(
            f"{path}: net {net_name!r} component labeled by {', '.join(sources)} "
            f"does not reach any {net_name!r} pin"
        )
    return errors


def add_trace_net_assertion_components(
    trace: Layer,
    assertions: Sequence[TraceNetAssertion],
    components: Mapping[Tuple[int, int], int],
    aliases: Mapping[str, VoxAlias],
    endpoint_components: Dict[str, List[Tuple[CellRef, int]]],
) -> None:
    for assertion in assertions:
        cell = (assertion.row_index, assertion.col)
        char = trace_char_at(trace, assertion.row_index, assertion.col)
        if not is_copper_char(char, aliases) or cell not in components:
            continue
        endpoint_components.setdefault(assertion.net_name, []).append(
            (
                CellRef(
                    row_label=assertion.row_label,
                    occurrence=1,
                    col=assertion.col,
                ),
                components[cell],
            )
        )


def validate_net_component_splits(
    path: Path,
    endpoint_components: Mapping[str, Sequence[Tuple[CellRef, int]]],
) -> List[str]:
    errors: List[str] = []
    for net_name, comps in endpoint_components.items():
        comp_ids = {comp for _, comp in comps}
        if len(comp_ids) <= 1:
            continue
        detail = ", ".join(
            f"{ref.row_label}:{ref.occurrence}.c{ref.col}->comp{comp}"
            for ref, comp in comps
        )
        errors.append(f"{path}: net {net_name!r} split across components: {detail}")
    return errors


def validate_trace_intents(
    path: Path,
    trace: Layer,
    intents: TraceIntents,
    max_col: int,
    aliases: Mapping[str, VoxAlias],
    net_aliases: Mapping[str, str],
) -> List[str]:
    errors: List[str] = []
    assertions, assertion_errors = extract_trace_net_assertions(
        trace,
        max_col,
        aliases,
        net_aliases,
    )
    errors.extend(assertion_errors)
    if not intents.nets and not intents.disjoint and not assertions:
        return errors
    errors.extend(validate_module_leg_short_risk(path, trace, max_col, aliases))
    row_index = build_row_label_index(trace)
    components = flood_fill_components(trace, max_col, aliases)
    pin_components = collect_pin_anchor_components(
        trace,
        max_col,
        components,
        assertions,
        aliases,
        net_aliases,
    )
    endpoint_components: Dict[str, List[Tuple[CellRef, int]]] = {}
    for net_name, endpoints in intents.nets.items():
        comps: List[Tuple[CellRef, int]] = []
        for ref in endpoints:
            try:
                cell = resolve_cell_ref(path, trace, ref, row_index, aliases)
            except ValueError as exc:
                errors.append(str(exc))
                continue
            if cell not in components:
                errors.append(
                    f"{path}: intent net {net_name!r} endpoint "
                    f"{ref.row_label}:{ref.occurrence}.c{ref.col} is isolated copper"
                )
                continue
            comp = components[cell]
            comps.append((ref, comp))
            char = trace_char_at(trace, cell[0], cell[1])
            if is_pad_char(char, aliases):
                pin_components.setdefault(net_name, []).append((ref, comp))
        endpoint_components[net_name] = comps
    add_trace_net_assertion_components(
        trace,
        assertions,
        components,
        aliases,
        endpoint_components,
    )
    errors.extend(
        validate_component_net_labels(
            path,
            trace,
            assertions,
            components,
            pin_components,
            aliases,
        )
    )
    for net_a, net_b in intents.disjoint:
        if net_a not in endpoint_components:
            errors.append(f"{path}: disjoint references unknown net {net_a!r}")
            continue
        if net_b not in endpoint_components:
            errors.append(f"{path}: disjoint references unknown net {net_b!r}")
            continue
        comps_a = {comp for _, comp in endpoint_components[net_a]}
        comps_b = {comp for _, comp in endpoint_components[net_b]}
        if comps_a & comps_b:
            errors.append(
                f"{path}: disjoint violation: nets {net_a!r} and {net_b!r} share "
                f"copper (components {sorted(comps_a & comps_b)})"
            )
    errors.extend(
        validate_trace_net_assertions(
            path,
            trace,
            assertions,
            components,
            endpoint_components,
            aliases,
        )
    )
    return errors


def validate_trace_col_assertions(
    path: Path,
    trace: Layer,
    aliases: Mapping[str, VoxAlias],
) -> List[str]:
    errors: List[str] = []
    max_col = inner_column_count(trace)
    for row_index, row in enumerate(trace.rows, 1):
        label = row_label(row, trace) or f"row {row_index}"
        assertions = extract_col_assertions(row)
        if not assertions:
            continue
        window = design_window(trace, row)
        for col, token in assertions:
            problem = validate_col_assertion(window, max_col, col, token, aliases)
            if problem is not None:
                errors.append(
                    f"{path}: trace row {row_index} ({label}) "
                    f"{col_label(col, trace)}={token}: {problem}"
                )
    return errors


def collect_pad_crowding_warnings(path: Path, layer_name: str, layer: Layer) -> List[str]:
    """Warn when adjacent */O pads may crowd routing on one row."""
    warnings: List[str] = []
    hint = "review crowding on this row"
    for row_index, row in enumerate(layer.rows, 1):
        label = row_label(row, layer) or f"row {row_index}"
        window = design_window(layer, row)
        for col in range(len(window) - 1):
            pair = window[col : col + 2]
            if pair not in {"*O", "O*"}:
                continue
            warnings.append(
                f"warn {path.name}: layer {layer_name!r} {label} "
                f"{col_label(col, layer)}-{col_label(col + 1, layer)}: "
                f"{pair} adjacency ({hint})"
            )
    return warnings


def collect_trace_pad_mismatch_warnings(
    path: Path,
    base: Layer,
    trace: Layer,
) -> List[str]:
    warnings: List[str] = []
    for row_index, (base_row, trace_row) in enumerate(zip(base.rows, trace.rows), 1):
        label = row_label(base_row, base) or row_label(trace_row, trace) or f"row {row_index}"
        base_window = design_window(base, base_row)
        trace_window = design_window(trace, trace_row)
        for col, (base_char, trace_char) in enumerate(zip(base_window, trace_window)):
            if trace_char not in PAD_CHARS:
                continue
            if base_char == trace_char:
                continue
            expected = base_char if base_char in PAD_CHARS else "no pad"
            actual = trace_char if trace_char in PAD_CHARS else "no pad"
            warnings.append(
                f"warn {path.name}: trace row {row_index} ({label}) "
                f"{col_label(col, trace)}: expected {expected!r} from base, got {actual!r}"
            )
    return warnings


def validate_row_labels_match(path: Path, base: Layer, trace: Layer) -> List[str]:
    errors: List[str] = []
    for row_index, (base_row, trace_row) in enumerate(zip(base.rows, trace.rows), 1):
        base_label = row_label(base_row, base)
        trace_label = row_label(trace_row, trace)
        if base_label != trace_label and (base_label is not None or trace_label is not None):
            errors.append(
                f"{path}: trace row {row_index}: left label {trace_label!r} "
                f"does not match base {base_label!r}"
            )
        base_right_label = right_row_label(base_row, base)
        trace_right_label = right_row_label(trace_row, trace)
        if base_right_label != trace_right_label and (
            base_right_label is not None or trace_right_label is not None
        ):
            errors.append(
                f"{path}: trace row {row_index}: right label {trace_right_label!r} "
                f"does not match base {base_right_label!r}"
            )
    return errors


def validate_layer_geometry(path: Path, layers: Mapping[str, Layer]) -> Tuple[Optional[Layer], Layer]:
    if TRACE_LAYER_NAME not in layers:
        raise ValueError(f"{path}: missing required layers: {TRACE_LAYER_NAME}")

    trace = layers[TRACE_LAYER_NAME]
    base = layers.get("base")
    if trace.height == 0 or trace.width == 0:
        raise ValueError(f"{path}: trace layer is empty")

    for layer_name, layer in layers.items():
        if layer.offset != trace.offset or layer.width != trace.width:
            raise ValueError(
                f"{path}: layer {layer_name!r} has geometry "
                f"({layer.offset}, {layer.width}); expected ({trace.offset}, {trace.width})"
            )
        if layer.height != trace.height:
            raise ValueError(
                f"{path}: layer {layer_name!r} declares {layer.height} rows; "
                f"expected {trace.height}"
            )
        if len(layer.rows) != trace.height:
            raise ValueError(
                f"{path}: layer {layer_name!r} has {len(layer.rows)} rows; "
                f"expected {trace.height}"
            )
        for row_index, row in enumerate(layer.rows, 1):
            if len(design_window(layer, row)) != trace.width:
                raise ValueError(f"{path}: layer {layer_name!r} row {row_index} has bad width")
    return base, trace


def should_validate_pico2w_hat_pin_notes(path: Path) -> bool:
    parts = path.parts
    return (
        path.name == "pico-side.vox"
        and len(parts) >= 4
        and parts[-4:] == ("hardware", "pico2w", "hat", path.name)
    )


def validate_pico2w_hat_pin_notes(path: Path, text: str) -> List[str]:
    if not should_validate_pico2w_hat_pin_notes(path):
        return []

    expected_notes: Mapping[str, Tuple[str, ...]] = {
        "AHT20 target": ("GP28", "SDA", "GP27", "SCL"),
        "IR TX target": ("GP10",),
        "IR RX target": ("GP13",),
    }
    stale_pairs: Mapping[str, Tuple[str, ...]] = {
        "AHT20 target": ("GP4/SDA", "GP5/SCL", "GP4 (SDA)", "GP5 (SCL)"),
        "IR TX target": ("GP14",),
        "IR RX target": ("GP15",),
    }
    errors: List[str] = []
    seen: Dict[str, int] = {note: 0 for note in expected_notes}
    for line_index, line in enumerate(text.splitlines(), 1):
        for note, tokens in expected_notes.items():
            if note not in line:
                continue
            seen[note] += 1
            missing = [token for token in tokens if token not in line]
            stale = [token for token in stale_pairs[note] if token in line]
            if missing or stale:
                detail_parts: List[str] = []
                if missing:
                    detail_parts.append(f"missing {', '.join(missing)}")
                if stale:
                    detail_parts.append(f"stale {', '.join(stale)}")
                errors.append(
                    f"{path}: line {line_index}: {note} pin note must match "
                    f"pico2w GP28 SDA, GP27 SCL, GP10 IR TX, GP13 IR RX "
                    f"({'; '.join(detail_parts)})"
                )
    for note, count in seen.items():
        if count == 0:
            errors.append(f"{path}: missing required pico2w hat pin note {note!r}")
    return errors


def validate(path: Path) -> List[str]:
    errors: List[str] = []
    warnings: List[str] = []
    text = path.read_text(encoding="utf-8")
    aliases = parse_vox_aliases_text(text)
    net_aliases = parse_net_aliases_text(text)
    layers = read_layers(path)
    base, trace = validate_layer_geometry(path, layers)
    max_col = inner_column_count(trace)

    if base is not None:
        errors.extend(validate_row_labels_match(path, base, trace))
        warnings.extend(collect_trace_pad_mismatch_warnings(path, base, trace))
    errors.extend(validate_trace_col_assertions(path, trace, aliases))
    intents = read_trace_intents(path, max_col, net_aliases)
    errors.extend(
        validate_trace_intents(
            path,
            trace,
            intents,
            max_col,
            aliases,
            net_aliases,
        )
    )
    errors.extend(validate_pico2w_hat_pin_notes(path, text))
    warning_layer = base if base is not None else trace
    warning_layer_name = "base" if base is not None else TRACE_LAYER_NAME
    warnings.extend(collect_pad_crowding_warnings(path, warning_layer_name, warning_layer))
    if errors:
        raise ValidationError(errors, warnings)
    print(f"ok {path.name}: {len(layers)} layers, {trace.width} x {trace.height}")
    return warnings


def default_vox_paths() -> List[Path]:
    repo_root = Path(__file__).resolve().parents[1]
    hardware_root = repo_root / "thermo" / "onboard" / "hardware"
    return sorted(hardware_root.glob("*/hat/*.vox"))


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("vox_paths", metavar="vox_path", nargs="*", type=Path)
    parser.add_argument(
        "--all",
        action="store_true",
        help="validate every hardware .vox file under thermo/onboard/hardware",
    )
    parser.add_argument(
        "-c",
        "--correct",
        action="store_true",
        help="rewrite ASCII trace shorthand as UTF-8 box drawing glyphs before validation",
    )
    args = parser.parse_args(argv[1:])
    if args.all and args.vox_paths:
        parser.error("--all cannot be combined with explicit vox_path arguments")
    if not args.all and not args.vox_paths:
        parser.error("the following arguments are required: vox_path (or use --all)")
    return args


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    paths = default_vox_paths() if args.all else args.vox_paths
    errors: List[str] = []
    for path in paths:
        try:
            if args.correct:
                correct_vox_file(path)
            for message in validate(path):
                print(message, file=sys.stderr)
        except ValidationError as exc:
            for message in exc.warnings:
                print(message, file=sys.stderr)
            errors.extend(exc.errors)
        except (OSError, UnicodeError, ValueError) as exc:
            errors.append(str(exc))
    if errors:
        for error in errors:
            for line in error.splitlines():
                print(f"error: {line}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
