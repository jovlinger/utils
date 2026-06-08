#!/usr/bin/env python3
"""Small dependency-free tests for vox2stl."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Sequence

import vox2stl

ROOT = Path(__file__).resolve().parent


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def layer_boxes(fixture_name: str) -> Sequence[vox2stl.BoxSolid]:
    path = ROOT / "testdata" / fixture_name
    layers = vox2stl.read_layers(path)
    layer = layers["trace"]
    unit = vox2stl.unit_from_file(path) or vox2stl.DEFAULT_UNIT_MM
    config = vox2stl.RenderConfig(unit_mm=unit)
    return vox2stl.build_boxes(layer, config)


def test_straight_fixture() -> None:
    boxes = layer_boxes("straight.vox")
    mesh = vox2stl.mesh_from_boxes(boxes)
    require(len(boxes) == 4, f"straight boxes: got {len(boxes)}")
    require(len(mesh.triangles) == 48, f"straight triangles: got {len(mesh.triangles)}")


def test_box_glyph_fixture() -> None:
    boxes = layer_boxes("box_glyphs.vox")
    mesh = vox2stl.mesh_from_boxes(boxes)
    require(len(boxes) == 33, f"box glyph boxes: got {len(boxes)}")
    require(len(mesh.triangles) == 396, f"box glyph triangles: got {len(mesh.triangles)}")


def test_pad_and_hole_defaults() -> None:
    require(
        abs(vox2stl.DEFAULT_TRACE_WIDTH_MM - vox2stl.DEFAULT_TRACE_WIDTH_FRAC * vox2stl.DEFAULT_UNIT_MM)
        < 1e-9,
        "trace width default should derive from UNIT fraction",
    )
    require(
        abs(
            vox2stl.DEFAULT_ADJACENT_ISOLATION_GAP_MM
            - vox2stl.DEFAULT_ADJACENT_ISOLATION_GAP_FRAC * vox2stl.DEFAULT_UNIT_MM
        )
        < 1e-9,
        "adjacent isolation gap should derive from UNIT fraction",
    )
    require(
        abs(vox2stl.DEFAULT_PAD_WIDTH_MM - vox2stl.DEFAULT_PIN_OUTSIDE_FRAC * vox2stl.DEFAULT_UNIT_MM)
        < 1e-9,
        "pin outside default should derive from UNIT fraction",
    )
    require(
        abs(vox2stl.DEFAULT_DEVICE_PAD_WIDTH_MM - vox2stl.DEFAULT_PAD_WIDTH_MM) < 1e-9,
        "device pad outer prism should match Pico pad outer prism",
    )
    require(
        abs(vox2stl.DEFAULT_DEVICE_HOLE_DIAMETER_MM - vox2stl.DEFAULT_PIN_HOLE_DIAMETER_MM * 1.25) < 1e-9,
        "device hole default should be 125 percent of Pico hole default",
    )
    require(
        abs(vox2stl.DEFAULT_LABEL_RECESS_MM - vox2stl.DEFAULT_LABEL_RECESS_FRAC * vox2stl.DEFAULT_UNIT_MM)
        < 1e-9,
        "label recess default should derive from UNIT fraction",
    )
    require(
        abs(vox2stl.DEFAULT_LABEL_HEIGHT_MM - vox2stl.DEFAULT_LABEL_HEIGHT_FRAC * vox2stl.DEFAULT_UNIT_MM)
        < 1e-9,
        "label height default should derive from UNIT fraction",
    )


def test_adjacent_pad_prisms_do_not_touch() -> None:
    config = vox2stl.RenderConfig()
    left = vox2stl.square_box(0.0, 0.0, config.device_pad_width_mm, config.trace_z0_mm, config.trace_z1_mm)
    right = vox2stl.square_box(
        config.unit_mm,
        0.0,
        config.device_pad_width_mm,
        config.trace_z0_mm,
        config.trace_z1_mm,
    )
    require(left.x1 < right.x0, "adjacent device pad prisms should have an air gap")


def test_effective_widths_respect_isolation_gap() -> None:
    config = vox2stl.RenderConfig()
    max_width = config.unit_mm - config.adjacent_isolation_gap_mm
    require(vox2stl.trace_width(config) <= max_width, "trace width should preserve no-connect gap")
    require(vox2stl.pad_width("*", config) <= max_width, "pin pad width should preserve no-connect gap")
    require(vox2stl.pad_width("O", config) <= max_width, "leg pad width should preserve no-connect gap")


def test_trace_arm_stops_before_hole_keepout() -> None:
    config = vox2stl.RenderConfig()
    arm = vox2stl.arm_box(0.0, 0.0, "E", config)
    next_hole = vox2stl.Hole(config.unit_mm, 0.0, config.device_hole_diameter_mm * 0.5)
    require(
        not vox2stl.box_intersects_hole(arm, next_hole),
        "trace arm protrusion should not encroach on next-cell through-hole void",
    )


def ensure_letter_tiles() -> None:
    if vox2stl.letter_tile_path("A").is_file():
        return
    import build_letter_tiles

    exit_code = build_letter_tiles.main()
    require(exit_code == 0, "letter tile build failed")


def test_letter_tile_manifest() -> None:
    ensure_letter_tiles()
    manifest = vox2stl.LETTER_TILES_DIR / "manifest.txt"
    require(manifest.is_file(), "letter tile manifest missing")
    text = manifest.read_text(encoding="ascii")
    require("source=hershey_simplex_smoothed" in text, "letter tile manifest should record smoothed Hershey source")
    require("A " in text, "letter tile manifest should list A")


def test_lowercase_letters_render_uppercase_label_shapes() -> None:
    ensure_letter_tiles()
    config = vox2stl.RenderConfig()
    layer = vox2stl.Layer("trace", 0, 3, 1, ("usb",))
    mesh, box_count, letter_count = vox2stl.build_layer_mesh(layer, config)
    require(box_count == 0, f"usb label boxes: got {box_count}")
    require(letter_count == 3, f"usb label cells: got {letter_count}")
    require(len(mesh.triangles) > 300, f"usb label triangles: got {len(mesh.triangles)}")
    require(len(mesh.triangles) <= 3 * 30000, f"usb label triangles exceed tile budget: {len(mesh.triangles)}")
    z0 = config.trace_z0_mm
    z1 = config.trace_z0_mm + config.label_height_mm
    require(
        all(min(a[2], b[2], c[2]) >= z0 - 1e-6 and max(a[2], b[2], c[2]) <= z1 + 1e-6 for a, b, c in mesh.triangles),
        "label triangles should use configured embossed height",
    )
    require(
        min(min(a[0], b[0], c[0]) for a, b, c in mesh.triangles)
        >= -1.5 * config.unit_mm + config.label_recess_mm - 1e-6,
        "label triangles should keep west recess",
    )
    require(
        max(max(a[0], b[0], c[0]) for a, b, c in mesh.triangles)
        <= 1.5 * config.unit_mm - config.label_recess_mm + 1e-6,
        "label triangles should keep east recess",
    )


def test_uppercase_letters_remain_unassigned() -> None:
    config = vox2stl.RenderConfig()
    layer = vox2stl.Layer("trace", 0, 3, 1, ("USB",))
    mesh, box_count, letter_count = vox2stl.build_layer_mesh(layer, config)
    require(box_count == 0, f"uppercase label source boxes: got {box_count}")
    require(letter_count == 0, f"uppercase label source cells: got {letter_count}")
    require(len(mesh.triangles) == 0, f"uppercase label source triangles: got {len(mesh.triangles)}")


def test_cli_writes_ascii_stl() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir) / "straight.stl"
        exit_code = vox2stl.run(
            [
                str(ROOT / "testdata" / "straight.vox"),
                "--output",
                str(out_path),
                "--solid-name",
                "straight_test",
            ]
        )
        text = out_path.read_text(encoding="ascii")
    require(exit_code == 0, f"CLI exit: got {exit_code}")
    require(text.startswith("solid straight_test\n"), "STL solid header missing")
    require(text.count("facet normal") == 48, "STL facet count mismatch")


def test_cli_writes_full_stl_with_holes() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir) / "straight-full.stl"
        exit_code = vox2stl.run(
            [
                str(ROOT / "testdata" / "straight.vox"),
                "--mode",
                "full",
                "--output",
                str(out_path),
                "--solid-name",
                "straight_full_test",
            ]
        )
        text = out_path.read_text(encoding="ascii")
    require(exit_code == 0, f"full CLI exit: got {exit_code}")
    require(text.startswith("solid straight_full_test\n"), "full STL solid header missing")
    require(text.count("facet normal") > 60, "full STL should include base and holes")


def main() -> int:
    test_straight_fixture()
    test_box_glyph_fixture()
    test_pad_and_hole_defaults()
    test_adjacent_pad_prisms_do_not_touch()
    test_effective_widths_respect_isolation_gap()
    test_trace_arm_stops_before_hole_keepout()
    test_letter_tile_manifest()
    test_lowercase_letters_render_uppercase_label_shapes()
    test_uppercase_letters_remain_unassigned()
    test_cli_writes_ascii_stl()
    test_cli_writes_full_stl_with_holes()
    print("ok vox2stl tests")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
