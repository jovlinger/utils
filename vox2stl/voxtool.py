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
from constants import correct_vox_shorthand_text

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
    current_rows: List[int] = []

    def finish_layer() -> None:
        nonlocal current_name, current_offset, current_width, current_rows
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
                )
            )
        current_name = None
        current_offset = None
        current_width = None
        current_rows = []

    for line_index, line in enumerate(lines):
        if not line or line.startswith("#"):
            continue
        stripped = line.strip()
        if (
            _check_vox.parse_alias_line(stripped) is not None
            or _check_vox.parse_net_alias_line(stripped) is not None
        ):
            continue
        header = _check_vox.parse_layer_header(line)
        if header is not None:
            finish_layer()
            current_name = header.name
            current_offset = header.offset
            current_width = header.width
            continue
        if line.startswith("layer "):
            finish_layer()
            continue
        if current_name is not None:
            current_rows.append(line_index)

    finish_layer()
    return layers


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
