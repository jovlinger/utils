#!/usr/bin/env python3
"""Validate and transform HAT text voxel design files. Newest version"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

import check_vox as _check_vox
import vox2stl as _vox2stl
from check_vox import *  # Re-export validator helpers for existing test coverage.
from constants import (
    LAYER_HEADER_RE,
    LAYER_KEY_ALIASES,
    LAYER_POSITIONAL_KEYS,
    PAD_CHARS,
    correct_vox_shorthand_text,
    is_vox_meta_line,
    parse_layer_header,
)

GLYPH_MIRROR: Mapping[str, str] = {
    "\u250c": "\u2510",
    "\u2510": "\u250c",
    "\u2514": "\u2518",
    "\u2518": "\u2514",
    "\u251c": "\u2524",
    "\u2524": "\u251c",
    "\u252c": "\u252c",
    "\u2534": "\u2534",
    "\u253c": "\u253c",
    "\u2500": "\u2500",
    "\u2502": "\u2502",
    "<": ">",
    ">": "<",
    "/": "\\",
    "\\": "/",
}
COL_EQUALS_RE = re.compile(
    r"(?P<prefix>\.?c)(?P<col>\d+)(?P<sep>\s*=\s*)"
    r"(?P<token>-\*|\*-|\||\+|-|<|>|\^|/|\\|"
    r"[\u250c\u2510\u2514\u2518\u251c\u2524\u252c\u2534\u253c\u2500\u2502])?"
)
ENDPOINT_RE = re.compile(r"\b(?P<label>[A-Za-z0-9_:-]+)\.c(?P<col>\d+)\b")
RIGHT_LABEL_RE = re.compile(r"^(?P<space>\s*)(?P<label>\S+)(?P<rest>.*)$")


@dataclass(frozen=True)
class LayerSpec:
    name: str
    offset: int
    width: int
    row_indexes: List[int]
    header_index: int = -1


@dataclass(frozen=True)
class LabelPair:
    left: Optional[str]
    right: Optional[str]


def split_line_ending(raw_line: str) -> Tuple[str, str]:
    if raw_line.endswith("\r\n"):
        return raw_line[:-2], "\r\n"
    if raw_line.endswith("\n") or raw_line.endswith("\r"):
        return raw_line[:-1], raw_line[-1]
    return raw_line, ""


def find_layer_specs(lines: Sequence[str]) -> List[LayerSpec]:
    layers: List[LayerSpec] = []
    current_name: Optional[str] = None
    current_offset: Optional[int] = None
    current_width: Optional[int] = None
    current_header_index: int = -1
    current_rows: List[int] = []

    def finish_layer() -> None:
        nonlocal current_name, current_offset, current_width, current_header_index
        nonlocal current_rows
        if (
            current_name is not None
            and current_offset is not None
            and current_width is not None
            and current_rows
        ):
            layers.append(
                LayerSpec(
                    name=current_name,
                    offset=current_offset,
                    width=current_width,
                    row_indexes=list(current_rows),
                    header_index=current_header_index,
                )
            )
        current_name = None
        current_offset = None
        current_width = None
        current_header_index = -1
        current_rows = []

    for line_index, line in enumerate(lines):
        if is_vox_meta_line(line):
            continue
        header = _check_vox.parse_layer_header(line)
        if header is not None:
            finish_layer()
            current_name = header.name
            current_offset = header.offset
            current_width = header.width
            current_header_index = line_index
            continue
        if line.startswith("layer "):
            finish_layer()
            continue
        if current_name is not None:
            current_rows.append(line_index)

    finish_layer()
    return layers


def rewrite_layer_header_fields(
    line: str,
    *,
    new_height: Optional[int] = None,
    new_offset: Optional[int] = None,
) -> str:
    """Rewrite selected layer header fields; preserve argument form."""
    parsed = parse_layer_header(line)
    if parsed is None:
        raise ValueError(f"not a layer header: {line!r}")
    if new_height is None and new_offset is None:
        return line
    if new_height is not None and parsed.height == new_height and new_offset is None:
        return line
    if new_offset is not None and parsed.offset == new_offset and new_height is None:
        return line
    if (
        new_height is not None
        and new_offset is not None
        and parsed.height == new_height
        and parsed.offset == new_offset
    ):
        return line
    match = LAYER_HEADER_RE.match(line)
    if match is None:
        raise ValueError(f"not a layer header: {line!r}")
    name = match.group(1)
    body = match.group(2).strip()
    parts: List[str] = []
    positional_index = 0
    for raw_part in body.split(","):
        part = raw_part.strip()
        if not part:
            raise ValueError(f"empty argument in layer header: {line!r}")
        if "=" in part:
            raw_key, _raw_value = part.split("=", 1)
            key_token = raw_key.strip()
            canonical = LAYER_KEY_ALIASES.get(key_token, key_token)
            if canonical == "height_rows" and new_height is not None:
                parts.append(f"{key_token}={new_height}")
            elif canonical == "horizontal_offset" and new_offset is not None:
                parts.append(f"{key_token}={new_offset}")
            else:
                parts.append(part)
        else:
            if positional_index >= len(LAYER_POSITIONAL_KEYS):
                raise ValueError(f"unexpected positional in layer header: {line!r}")
            key = LAYER_POSITIONAL_KEYS[positional_index]
            if key == "height_rows" and new_height is not None:
                parts.append(str(new_height))
            elif key == "horizontal_offset" and new_offset is not None:
                parts.append(str(new_offset))
            else:
                parts.append(part)
            positional_index += 1
    return f"layer {name} ({', '.join(parts)})"


def rewrite_layer_header_height(line: str, new_height: int) -> str:
    return rewrite_layer_header_fields(line, new_height=new_height)


def indent_row_margin(row: str, offset: int, width: int, delta: int) -> str:
    """Shift a layer row's design window by changing the left margin width."""
    end = offset + width
    padded = row.ljust(end)
    left = padded[:offset]
    design = padded[offset:end]
    right = row[end:] if len(row) > end else ""
    new_offset = offset + delta
    if new_offset < 0:
        raise ValueError(f"indent delta {delta} would make horizontal_offset negative")
    label = left.rstrip()
    if len(label) > new_offset:
        raise ValueError(
            f"left label {label!r} does not fit in offset {new_offset}"
        )
    if delta >= 0:
        new_left = left + (" " * delta)
    else:
        remove = -delta
        if not left.endswith(" " * remove):
            raise ValueError(
                f"cannot outdent by {remove}: left margin {left!r} lacks trailing spaces"
            )
        new_left = left[:-remove]
    return f"{new_left}{design}{right}"


def indent_vox_text(text: str, delta: int) -> str:
    """Adjust horizontal_offset by delta on every layer; shift row left margins."""
    if delta == 0:
        return text
    split_lines = [split_line_ending(raw_line) for raw_line in text.splitlines(keepends=True)]
    lines = [line for line, _ in split_lines]
    endings = [ending for _, ending in split_lines]
    layers = find_layer_specs(lines)
    if not layers:
        raise ValueError("no layers found")

    reference = layers[0]
    for layer in layers[1:]:
        if layer.offset != reference.offset or layer.width != reference.width:
            raise ValueError(
                f"cross-layer geometry mismatch: layer {layer.name!r} has "
                f"({layer.offset}, {layer.width}); expected "
                f"({reference.offset}, {reference.width}) from {reference.name!r}"
            )

    new_offset = reference.offset + delta
    if new_offset < 0:
        raise ValueError(f"indent delta {delta} would make horizontal_offset negative")

    for layer in layers:
        if layer.header_index < 0:
            raise ValueError(f"layer {layer.name!r} missing header index")
        lines[layer.header_index] = rewrite_layer_header_fields(
            lines[layer.header_index], new_offset=new_offset
        )
        for row_index in layer.row_indexes:
            lines[row_index] = indent_row_margin(
                lines[row_index], layer.offset, layer.width, delta
            )

    return "".join(line + ending for line, ending in zip(lines, endings))


def reheader_vox_text(text: str) -> str:
    """Set each layer header height_rows to the data row count (read_layers rules)."""
    split_lines = [split_line_ending(raw_line) for raw_line in text.splitlines(keepends=True)]
    lines = [line for line, _ in split_lines]
    endings = [ending for _, ending in split_lines]
    layers = find_layer_specs(lines)
    if not layers:
        raise ValueError("no layers found")

    reference = layers[0]
    for layer in layers[1:]:
        if layer.offset != reference.offset or layer.width != reference.width:
            raise ValueError(
                f"cross-layer geometry mismatch: layer {layer.name!r} has "
                f"({layer.offset}, {layer.width}); expected "
                f"({reference.offset}, {reference.width}) from {reference.name!r}"
            )

    for layer in layers:
        if layer.header_index < 0:
            raise ValueError(f"layer {layer.name!r} missing header index")
        new_height = len(layer.row_indexes)
        lines[layer.header_index] = rewrite_layer_header_height(
            lines[layer.header_index], new_height
        )

    return "".join(line + ending for line, ending in zip(lines, endings))


def sync_pads_row(src_row: str, dst_row: str, offset: int, width: int) -> str:
    """Upsert * / O from src design window into dst; leave non-pad src cells alone."""
    end = offset + width
    src_design = src_row.ljust(end)[offset:end]
    padded_dst = dst_row.ljust(end)
    left = padded_dst[:offset]
    design = list(padded_dst[offset:end])
    right = dst_row[end:] if len(dst_row) > end else ""
    for col, char in enumerate(src_design):
        if char in PAD_CHARS:
            design[col] = char
    return f"{left}{''.join(design)}{right}"


def sync_pads_vox_text(text: str, from_layer: str, to_layer: str) -> str:
    """Copy * / O cells from one layer's design window into another's (upsert only)."""
    if from_layer == to_layer:
        raise ValueError("--from and --to must name different layers")
    split_lines = [split_line_ending(raw_line) for raw_line in text.splitlines(keepends=True)]
    lines = [line for line, _ in split_lines]
    endings = [ending for _, ending in split_lines]
    layers = {layer.name: layer for layer in find_layer_specs(lines)}
    if from_layer not in layers:
        raise ValueError(f"source layer {from_layer!r} not found")
    if to_layer not in layers:
        raise ValueError(f"destination layer {to_layer!r} not found")
    source = layers[from_layer]
    dest = layers[to_layer]
    if source.offset != dest.offset or source.width != dest.width:
        raise ValueError(
            f"layers {from_layer!r} and {to_layer!r} disagree on geometry "
            f"({source.offset}, {source.width}) vs ({dest.offset}, {dest.width})"
        )
    if len(source.row_indexes) != len(dest.row_indexes):
        raise ValueError(
            f"layers {from_layer!r} and {to_layer!r} disagree on row count "
            f"({len(source.row_indexes)} vs {len(dest.row_indexes)})"
        )
    for src_index, dst_index in zip(source.row_indexes, dest.row_indexes):
        lines[dst_index] = sync_pads_row(
            lines[src_index], lines[dst_index], dest.offset, dest.width
        )
    return "".join(line + ending for line, ending in zip(lines, endings))


def mirror_chars(text: str) -> str:
    return "".join(GLYPH_MIRROR.get(char, char) for char in reversed(text))


def mirror_col_equals(text: str, max_col: int) -> str:
    def repl(match: re.Match[str]) -> str:
        col = int(match.group("col"))
        if 1 <= col <= max_col:
            col = max_col + 1 - col
        token = match.group("token") or ""
        if token == "*-":
            token = "-*"
        elif token == "-*":
            token = "*-"
        else:
            token = GLYPH_MIRROR.get(token, token)
        return f"{match.group('prefix')}{col}{match.group('sep')}{token}"

    return COL_EQUALS_RE.sub(repl, text)


def split_left_label(prefix: str) -> Optional[str]:
    stripped = prefix.strip()
    return stripped or None


def split_right_label(suffix: str) -> Tuple[Optional[str], str]:
    match = RIGHT_LABEL_RE.match(suffix)
    if match is None:
        return None, suffix
    label = match.group("label")
    if label.startswith("#"):
        return None, suffix
    return label, match.group("rest")


def format_left_label(label: Optional[str], offset: int) -> str:
    if label is None:
        return " " * offset
    if len(label) > offset:
        raise ValueError(f"cannot fit mirrored left label {label!r} in offset {offset}")
    return label.ljust(offset)


def format_right_label(label: Optional[str], rest: str) -> str:
    if label is None:
        return rest
    return f" {label}{rest}"


def mirror_layer_row(line: str, offset: int, width: int) -> Tuple[str, LabelPair]:
    end = offset + width
    padded = line.ljust(end)
    left_label = split_left_label(padded[:offset])
    body = padded[offset:end]
    right_label, rest = split_right_label(line[end:])
    max_col = max(0, width - 2)
    mirrored_body = mirror_chars(body)
    mirrored_rest = mirror_col_equals(rest, max_col)
    return (
        f"{format_left_label(right_label, offset)}"
        f"{mirrored_body}"
        f"{format_right_label(left_label, mirrored_rest)}",
        LabelPair(left=left_label, right=right_label),
    )


def split_occurrence(label: str) -> Tuple[str, int, bool]:
    if ":" not in label:
        return label, 1, False
    base, _, occurrence_text = label.rpartition(":")
    if not occurrence_text.isdigit():
        return label, 1, False
    return base, int(occurrence_text), True


def build_label_maps(label_pairs: Sequence[LabelPair]) -> Tuple[Dict[str, str], Dict[Tuple[str, int], Tuple[str, int]]]:
    simple: Dict[str, str] = {}
    occurrence: Dict[Tuple[str, int], Tuple[str, int]] = {}
    left_counts: Dict[str, int] = {}
    right_counts: Dict[str, int] = {}

    for pair in label_pairs:
        left_index: Optional[int] = None
        right_index: Optional[int] = None
        if pair.left is not None:
            left_counts[pair.left] = left_counts.get(pair.left, 0) + 1
            left_index = left_counts[pair.left]
        if pair.right is not None:
            right_counts[pair.right] = right_counts.get(pair.right, 0) + 1
            right_index = right_counts[pair.right]
        if pair.left is not None and pair.right is not None:
            simple.setdefault(pair.left, pair.right)
            simple.setdefault(pair.right, pair.left)
            if left_index is not None and right_index is not None:
                occurrence[(pair.left, left_index)] = (pair.right, right_index)
                occurrence[(pair.right, right_index)] = (pair.left, left_index)
    return simple, occurrence


def mirror_endpoint_text(
    text: str,
    max_col: int,
    label_map: Mapping[str, str],
    occurrence_map: Mapping[Tuple[str, int], Tuple[str, int]],
) -> str:
    def repl(match: re.Match[str]) -> str:
        label, occurrence, explicit_occurrence = split_occurrence(match.group("label"))
        mapped_label = label_map.get(label, label)
        mapped_occurrence = occurrence
        if (label, occurrence) in occurrence_map:
            mapped_label, mapped_occurrence = occurrence_map[(label, occurrence)]

        col = int(match.group("col"))
        if 1 <= col <= max_col:
            col = max_col + 1 - col
        if explicit_occurrence:
            return f"{mapped_label}:{mapped_occurrence}.c{col}"
        return f"{mapped_label}.c{col}"

    return ENDPOINT_RE.sub(repl, text)


def mirror_vox_text(text: str) -> str:
    split_lines = [split_line_ending(raw_line) for raw_line in text.splitlines(keepends=True)]
    lines = [line for line, _ in split_lines]
    endings = [ending for _, ending in split_lines]
    layers = find_layer_specs(lines)
    row_indexes = {line_index for layer in layers for line_index in layer.row_indexes}
    trace_label_pairs: List[LabelPair] = []
    trace_width = 0

    for layer in layers:
        label_pairs: List[LabelPair] = []
        for line_index in layer.row_indexes:
            mirrored, label_pair = mirror_layer_row(lines[line_index], layer.offset, layer.width)
            lines[line_index] = mirrored
            label_pairs.append(label_pair)
        if layer.name == _check_vox.TRACE_LAYER_NAME:
            trace_label_pairs = label_pairs
            trace_width = layer.width

    if trace_width:
        max_col = max(0, trace_width - 2)
        label_map, occurrence_map = build_label_maps(trace_label_pairs)
        for line_index, line in enumerate(lines):
            if line_index in row_indexes:
                continue
            lines[line_index] = mirror_endpoint_text(line, max_col, label_map, occurrence_map)

    return "".join(line + ending for line, ending in zip(lines, endings))


def write_transformed_text(
    path: Path,
    out_path: Optional[Path],
    transform_name: str,
    transform: Callable[[str], str],
) -> None:
    destination = out_path or path
    text = path.read_text(encoding="utf-8")
    transformed = transform(text)
    destination.write_text(transformed, encoding="utf-8")
    print(f"ok {transform_name} {path} -> {destination}")


def run_check(args: argparse.Namespace) -> int:
    paths = _check_vox.default_vox_paths() if args.all else args.vox_paths
    errors: List[str] = []
    for path in paths:
        try:
            for message in _check_vox.validate(path):
                print(message, file=sys.stderr)
        except _check_vox.ValidationError as exc:
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


def run_correct(args: argparse.Namespace) -> int:
    try:
        write_transformed_text(
            args.vox_path,
            args.out,
            "corrected",
            correct_vox_shorthand_text,
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def run_mirror(args: argparse.Namespace) -> int:
    try:
        write_transformed_text(args.vox_path, args.out, "mirrored", mirror_vox_text)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def run_reheader(args: argparse.Namespace) -> int:
    try:
        write_transformed_text(args.vox_path, args.out, "reheadered", reheader_vox_text)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def run_sync_pads(args: argparse.Namespace) -> int:
    try:
        write_transformed_text(
            args.vox_path,
            args.out,
            "sync-pads",
            lambda text: sync_pads_vox_text(text, args.from_layer, args.to_layer),
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def run_indent(args: argparse.Namespace) -> int:
    try:
        write_transformed_text(
            args.vox_path,
            args.out,
            "indented",
            lambda text: indent_vox_text(text, args.delta),
        )
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 0


def run_stl(args: argparse.Namespace) -> int:
    try:
        return _vox2stl.run_from_args(args)
    except (OSError, UnicodeError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser("check", help="validate .vox files")
    check.add_argument("vox_paths", metavar="vox_path", nargs="*", type=Path)
    check.add_argument(
        "--all",
        action="store_true",
        help="validate every hardware .vox file under thermo/onboard/hardware",
    )
    check.set_defaults(func=run_check)

    correct = subparsers.add_parser("correct", help="normalize shorthand in a .vox file")
    correct.add_argument("vox_path", metavar="filepath", type=Path)
    correct.add_argument("-out", "--out", type=Path, help="write to this path instead of in place")
    correct.set_defaults(func=run_correct)

    mirror = subparsers.add_parser("mirror", help="mirror a .vox file left to right")
    mirror.add_argument("vox_path", metavar="filepath", type=Path)
    mirror.add_argument("-out", "--out", type=Path, help="write to this path instead of in place")
    mirror.set_defaults(func=run_mirror)

    reheader = subparsers.add_parser(
        "reheader",
        help="rewrite layer height_rows to match actual data row counts",
    )
    reheader.add_argument("vox_path", metavar="filepath", type=Path)
    reheader.add_argument("-out", "--out", type=Path, help="write to this path instead of in place")
    reheader.set_defaults(func=run_reheader)

    sync_pads = subparsers.add_parser(
        "sync-pads",
        help="upsert * / O pads from one layer design window into another",
    )
    sync_pads.add_argument("vox_path", metavar="filepath", type=Path)
    sync_pads.add_argument(
        "--from",
        dest="from_layer",
        required=True,
        metavar="LAYER",
        help="source layer name (typically base or trace)",
    )
    sync_pads.add_argument(
        "--to",
        dest="to_layer",
        required=True,
        metavar="LAYER",
        help="destination layer name (typically base or trace)",
    )
    sync_pads.add_argument("-out", "--out", type=Path, help="write to this path instead of in place")
    sync_pads.set_defaults(func=run_sync_pads)

    indent = subparsers.add_parser(
        "indent",
        help="shift horizontal_offset and left margins by --delta (negative outdents)",
    )
    indent.add_argument("vox_path", metavar="filepath", type=Path)
    indent.add_argument(
        "--delta",
        type=int,
        required=True,
        help="columns to add to horizontal_offset (use a negative value to outdent)",
    )
    indent.add_argument("-out", "--out", type=Path, help="write to this path instead of in place")
    indent.set_defaults(func=run_indent)

    stl = subparsers.add_parser("stl", help="generate ASCII STL geometry from a .vox file")
    _vox2stl.add_cli_arguments(stl)
    stl.set_defaults(func=run_stl)

    args = parser.parse_args(argv[1:])
    if args.command == "check":
        if args.all and args.vox_paths:
            parser.error("check --all cannot be combined with explicit vox_path arguments")
        if not args.all and not args.vox_paths:
            parser.error("check requires filepath (or use --all)")
    return args


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
