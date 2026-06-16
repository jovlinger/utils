#!/usr/bin/env python3
"""Small dependency-free tests for vox2stl."""

from __future__ import annotations

import contextlib
import gzip
import io
import pickle
import tempfile
from pathlib import Path
from typing import Sequence, Tuple

import voxtool
import vox2stl
from constants import (
    BOX_LL,
    BOX_LR,
    BOX_T_LEFT,
    BOX_T_RIGHT,
    BOX_T_UP,
    BOX_UL,
    BOX_UR,
    correct_vox_shorthand_text,
)

ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
PICO_UP_SIDE_FIXTURE = REPO_ROOT / "thermo" / "onboard" / "hardware" / "pico2w" / "hat" / "up-side.vox"


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


def z_values(triangles: Sequence[vox2stl.Tri]) -> set[float]:
    return {round(vertex[2], 6) for triangle in triangles for vertex in triangle}


def box_x_bounds(boxes: Sequence[vox2stl.BoxSolid]) -> Tuple[float, float]:
    return min(box.x0 for box in boxes), max(box.x1 for box in boxes)


def point_in_triangle_xy(point: Tuple[float, float], triangle: vox2stl.Tri) -> bool:
    px, py = point
    (ax, ay, _), (bx, by, _), (cx, cy, _) = triangle
    denominator = (by - cy) * (ax - cx) + (cx - bx) * (ay - cy)
    if abs(denominator) < 1e-12:
        return False
    alpha = ((by - cy) * (px - cx) + (cx - bx) * (py - cy)) / denominator
    beta = ((cy - ay) * (px - cx) + (ax - cx) * (py - cy)) / denominator
    gamma = 1.0 - alpha - beta
    return alpha >= -1e-9 and beta >= -1e-9 and gamma >= -1e-9


def horizontal_triangle_covers_xy(triangle: vox2stl.Tri, z: float, point: Tuple[float, float]) -> bool:
    if any(abs(vertex[2] - z) > 1e-6 for vertex in triangle):
        return False
    return point_in_triangle_xy(point, triangle)


def test_straight_fixture() -> None:
    boxes = layer_boxes("straight.vox")
    mesh = vox2stl.mesh_from_boxes(boxes)
    require(len(boxes) == 5, f"straight boxes: got {len(boxes)}")
    require(len(mesh.triangles) == 60, f"straight triangles: got {len(mesh.triangles)}")


def test_box_glyph_fixture() -> None:
    boxes = layer_boxes("box_glyphs.vox")
    mesh = vox2stl.mesh_from_boxes(boxes)
    require(len(boxes) == 33, f"box glyph boxes: got {len(boxes)}")
    require(len(mesh.triangles) == 396, f"box glyph triangles: got {len(mesh.triangles)}")


def test_voxtool_stl_base_trace_fixture_outputs_two_layer_mesh_by_default() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        output_path = Path(tmp_dir) / "up-side.stl"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(
                [
                    "voxtool.py",
                    "stl",
                    str(PICO_UP_SIDE_FIXTURE),
                    "--output",
                    str(output_path),
                ]
            )
        triangles = vox2stl.read_ascii_stl(output_path)

    z_levels = z_values(triangles)
    require(exit_code == 0, f"voxtool stl exit: got {exit_code}; {stderr.getvalue()}")
    require(round(vox2stl.DEFAULT_BASE_Z0_MM, 6) in z_levels, "STL should include substrate bottom")
    require(round(vox2stl.DEFAULT_BASE_Z1_MM, 6) in z_levels, "STL should include substrate top")
    require(round(vox2stl.DEFAULT_TRACE_Z1_MM, 6) in z_levels, "STL should include raised trace top")


def test_pad_and_hole_defaults() -> None:
    require(
        abs(vox2stl.DEFAULT_LAYER_THICKNESS_MM - 2.5) < 1e-9,
        "default layer thickness should be 2.5 mm",
    )
    require(
        abs(vox2stl.DEFAULT_BASE_Z1_MM - vox2stl.DEFAULT_LAYER_THICKNESS_MM) < 1e-9,
        "base top should derive from default layer thickness",
    )
    require(
        abs(vox2stl.DEFAULT_TRACE_Z1_MM - 2.0 * vox2stl.DEFAULT_LAYER_THICKNESS_MM) < 1e-9,
        "trace top should derive from two default layers",
    )
    require(
        abs(vox2stl.DEFAULT_TRACE_WIDTH_FRAC - 0.72 * (0.72 / 0.88)) < 1e-9,
        "trace width default should shrink by the pad exterior ratio",
    )
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
        abs(vox2stl.DEFAULT_PIN_OUTSIDE_FRAC - 0.88) < 1e-9,
        "pin outside default should reduce pad setback from the unit edge",
    )
    require(
        abs(vox2stl.DEFAULT_LEG_OUTSIDE_FRAC - 0.88) < 1e-9,
        "device outside default should reduce pad setback from the unit edge",
    )
    require(
        abs(vox2stl.DEFAULT_DEVICE_PAD_WIDTH_MM - vox2stl.DEFAULT_PAD_WIDTH_MM) < 1e-9,
        "device pad outer prism should match Pico pad outer prism",
    )
    require(
        abs(vox2stl.DEFAULT_PIN_HOLE_DIAMETER_MM - 1.10 * 0.66 * 1.50) < 1e-9,
        "pin hole default should be an absolute physical diameter",
    )
    require(
        abs(vox2stl.DEFAULT_DEVICE_HOLE_DIAMETER_MM - 1.10) < 1e-9,
        "device hole default should be an absolute physical diameter",
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
    require(
        abs(vox2stl.DEFAULT_COND_LIG_MM - vox2stl.DEFAULT_COND_LIG_FRAC * vox2stl.DEFAULT_UNIT_MM)
        < 1e-9,
        "same-copper ligature length should derive from UNIT fraction",
    )
    require(
        abs(vox2stl.DEFAULT_ISOL_LIG_MM - vox2stl.DEFAULT_ISOL_LIG_FRAC * vox2stl.DEFAULT_UNIT_MM)
        < 1e-9,
        "different-copper ligature cut should derive from UNIT fraction",
    )
    require(
        abs(vox2stl.DEFAULT_GRID_MM - 0.04 * vox2stl.DEFAULT_UNIT_MM) < 1e-9,
        "subtractive grid pitch should keep hole cuts high resolution",
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


def test_trace_arm_overlaps_connected_pad() -> None:
    config = vox2stl.RenderConfig()
    layer = vox2stl.Layer("trace", 0, 2, 1, ("-*",))
    trace_cx, trace_cy = vox2stl.cell_center(layer, 0, 0, config)
    pad_cx, _ = vox2stl.cell_center(layer, 0, 1, config)
    trace_boxes = vox2stl.glyph_boxes(layer, 0, 0, "-", trace_cx, trace_cy, config)
    pad_x0 = pad_cx - vox2stl.pad_width("*", config) * 0.5
    require(
        max(box.x1 for box in trace_boxes) > pad_x0,
        "connected trace arm should overlap the neighboring pad footprint",
    )


def test_full_mesh_subtracts_pad_hole_after_connected_trace_addition() -> None:
    config = vox2stl.RenderConfig()
    base_layer = vox2stl.Layer("base", 0, 2, 1, (".*",))
    trace_layer = vox2stl.Layer("trace", 0, 2, 1, ("-*",))
    pad_center = vox2stl.cell_center(trace_layer, 0, 1, config)
    mesh, hole_count, box_count, _ = vox2stl.full_mesh_from_layers(base_layer, trace_layer, config)
    filled_top = any(
        horizontal_triangle_covers_xy(triangle, config.trace_z1_mm, pad_center)
        for triangle in mesh.triangles
    )
    require(hole_count == 1, f"pad hole count: got {hole_count}")
    require(box_count > 0, "trace layout should add copper before subtracting the hole")
    require(not filled_top, "final trace top should keep the connected pad hole open")


def test_keyword_layer_header_and_thickness_override() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "thickness.vox"
        path.write_text(
            "\n".join(
                [
                    "layer base (horizontal_offset=0, width_columns=1, height_rows=1, layer_thickness_mm=1.25)",
                    "X",
                    "",
                    "layer trace (horizontal_offset=0, width_columns=1, height_rows=1, layer_thickness_mm=0.75, letter_style=negative)",
                    "*",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        layers = vox2stl.read_layers(path)

    require(layers["base"].offset == 0, "keyword layer header should parse offset")
    require(layers["base"].width == 1, "keyword layer header should parse width")
    require(layers["base"].height == 1, "keyword layer header should parse height")
    require(
        abs(layers["base"].layer_thickness_mm - 1.25) < 1e-9,
        "base layer should carry header thickness",
    )
    require(
        abs(layers["trace"].layer_thickness_mm - 0.75) < 1e-9,
        "trace layer should carry header thickness",
    )
    require(layers["base"].letter_style == "positive", "base layer should default to positive letters")
    require(layers["trace"].letter_style == "negative", "trace layer should carry letter style")


def test_full_mesh_uses_layer_thickness_overrides() -> None:
    base_layer = vox2stl.Layer(
        "base",
        0,
        1,
        1,
        ("X",),
        layer_thickness_mm=1.25,
    )
    trace_layer = vox2stl.Layer(
        "trace",
        0,
        1,
        1,
        ("*",),
        layer_thickness_mm=0.75,
    )
    mesh, _, _, _ = vox2stl.full_mesh_from_layers(base_layer, trace_layer, vox2stl.RenderConfig())
    levels = z_values(mesh.triangles)

    require(0.0 in levels, "mesh should include base bottom")
    require(1.25 in levels, "mesh should include base top from layer thickness")
    require(2.0 in levels, "mesh should include trace top from layer thickness")


def test_trace_air_gap_voids_mark_disconnected_neighboring_copper() -> None:
    config = vox2stl.RenderConfig()
    disconnected_layer = vox2stl.Layer("trace", 0, 2, 1, ("-|",))
    connected_layer = vox2stl.Layer("trace", 0, 2, 1, ("--",))
    require(
        len(vox2stl.trace_air_gap_voids(disconnected_layer, config)) == 1,
        "disconnected neighboring copper should collect one isolation void",
    )
    require(
        len(vox2stl.trace_air_gap_voids(connected_layer, config)) == 0,
        "connected neighboring copper should not collect an isolation void",
    )


def test_ligature_keys_encode_same_different_and_empty_neighbors() -> None:
    config = vox2stl.RenderConfig()
    connected_layer = vox2stl.Layer("trace", 0, 2, 1, ("--",))
    isolated_layer = vox2stl.Layer("trace", 0, 2, 1, ("-|",))
    pad_layer = vox2stl.Layer("trace", 0, 2, 1, ("OO",))
    require(
        vox2stl.ligature_key_for_cell(connected_layer, 0, 0, "-", config) == ("-", 0, 1, 0, 0),
        "connected east neighbor should become same-copper state",
    )
    require(
        vox2stl.ligature_key_for_cell(isolated_layer, 0, 0, "-", config) == ("-", 0, -1, 0, 0),
        "mismatched east neighbor should become different-copper state",
    )
    require(
        vox2stl.ligature_key_for_cell(pad_layer, 0, 0, "O", config) == ("O", 0, -1, 0, 0),
        "adjacent pads should isolate from each other",
    )


def test_isolation_ligature_width_uses_pad_width() -> None:
    config = vox2stl.RenderConfig()
    require(
        vox2stl.isolation_ligature_width(config) == max(vox2stl.pad_width("*", config), vox2stl.pad_width("O", config)),
        "different-copper isolation cuts should use pad width",
    )
    require(
        vox2stl.isolation_ligature_width(config) > vox2stl.trace_width(config),
        "different-copper isolation cuts should be wider than trace ligatures",
    )


def test_tile_cache_persists_naive_letters_and_ligatures() -> None:
    ensure_letter_tiles()
    old_path = vox2stl.TILE_CACHE_PATH
    old_cache = vox2stl._PERSISTENT_TILE_CACHE
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_path = Path(tmp_dir) / "tile_cache.pickle"
            vox2stl.TILE_CACHE_PATH = cache_path
            vox2stl._PERSISTENT_TILE_CACHE = None
            config = vox2stl.RenderConfig()
            key = ("-", 0, 1, 0, 0)
            letter_tris = vox2stl.cached_tile_tris("u", config)
            ligature_tris = vox2stl.cached_tile_tris(key, config)
            require(cache_path.read_bytes().startswith(b"\x1f\x8b"), "tile cache should be gzip-compressed")
            with gzip.open(cache_path, "rb") as file_obj:
                cache = pickle.load(file_obj)
        require(len(letter_tris) > 0, "cached naive letter should have triangles")
        require(len(ligature_tris) > 0, "cached ligature should have triangles")
        require("u" in cache, "tile cache should persist single-character letter keys")
        require("-" in cache, "tile cache should seed single-character copper keys before ligatures")
        require(key in cache, "tile cache should persist five-part ligature keys")
    finally:
        vox2stl.TILE_CACHE_PATH = old_path
        vox2stl._PERSISTENT_TILE_CACHE = old_cache


def test_missing_letter_stl_generates_cache_tile_automatically() -> None:
    old_dir = vox2stl.LETTER_TILES_DIR
    old_cache = vox2stl._LETTER_TILE_CACHE.copy()
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            vox2stl.LETTER_TILES_DIR = Path(tmp_dir)
            vox2stl._LETTER_TILE_CACHE.clear()
            tris = vox2stl.render_naive_tile("u", vox2stl.RenderConfig())
        require(len(tris) > 0, "missing pre-rendered letter STL should regenerate a letter tile")
    finally:
        vox2stl.LETTER_TILES_DIR = old_dir
        vox2stl._LETTER_TILE_CACHE.clear()
        vox2stl._LETTER_TILE_CACHE.update(old_cache)


def test_pad_tail_overlaps_connected_trace_without_joining_adjacent_pads() -> None:
    config = vox2stl.RenderConfig()
    connected_layer = vox2stl.Layer("trace", 0, 2, 1, ("O-",))
    pad_cx, pad_cy = vox2stl.cell_center(connected_layer, 0, 0, config)
    trace_cx, _ = vox2stl.cell_center(connected_layer, 0, 1, config)
    pad_boxes = vox2stl.glyph_boxes(connected_layer, 0, 0, "O", pad_cx, pad_cy, config)
    boundary_x = (pad_cx + trace_cx) * 0.5
    require(
        max(box.x1 for box in pad_boxes) > boundary_x,
        "connected pad should grow into the neighboring trace tile",
    )

    isolated_layer = vox2stl.Layer("trace", 0, 2, 1, ("OO",))
    isolated_boxes = vox2stl.build_boxes(isolated_layer, config)
    require(len(isolated_boxes) == 2, f"adjacent isolated pads should not grow tails: got {len(isolated_boxes)}")


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


def test_negative_base_letters_create_recess_without_changing_positive_default() -> None:
    config = vox2stl.RenderConfig()
    positive_layer = vox2stl.Layer("base", 0, 1, 1, ("f",))
    negative_layer = vox2stl.Layer("base", 0, 1, 1, ("f",), letter_style="negative")
    positive_mesh, positive_holes = vox2stl.build_base_mesh(positive_layer, config)
    negative_mesh, negative_holes = vox2stl.build_base_mesh(negative_layer, config)
    recess_z0 = round(config.base_z1_mm - config.label_height_mm, 6)

    require(positive_holes == 0, f"positive base letter holes: got {positive_holes}")
    require(negative_holes == 0, f"negative base letter holes: got {negative_holes}")
    require(
        recess_z0 not in z_values(positive_mesh.triangles),
        "positive base letter should remain a plain base tile",
    )
    require(
        recess_z0 in z_values(negative_mesh.triangles),
        "negative base letter should expose a recessed imprint floor",
    )
    require(
        len(negative_mesh.triangles) > len(positive_mesh.triangles),
        "negative base letter should add imprint wall and floor triangles",
    )


def test_negative_letter_voids_mirror_individual_shape_left_to_right() -> None:
    config = vox2stl.RenderConfig()
    normal_voids = vox2stl.letter_footprint_voids(
        "f",
        config,
        z0=0.0,
        z1=1.0,
        mirror_x=False,
    )
    mirrored_voids = vox2stl.letter_footprint_voids(
        "f",
        config,
        z0=0.0,
        z1=1.0,
        mirror_x=True,
    )
    normal_min_x, normal_max_x = box_x_bounds(normal_voids)
    mirrored_min_x, mirrored_max_x = box_x_bounds(mirrored_voids)

    require(abs(mirrored_min_x + normal_max_x) < 1e-6, "mirrored letter should flip west bound")
    require(abs(mirrored_max_x + normal_min_x) < 1e-6, "mirrored letter should flip east bound")


def test_correct_vox_shorthand_direct_t_junctions() -> None:
    text = "# <^> remains ASCII in comments\nlayer trace (0, 3, 1)\n<^>\n"
    corrected = correct_vox_shorthand_text(text)
    require("# <^> remains ASCII in comments\n" in corrected, "comments should not be corrected")
    require(
        f"{BOX_T_LEFT}{BOX_T_UP}{BOX_T_RIGHT}" in corrected,
        "direct T shorthand should become box drawing glyphs",
    )


def test_correct_vox_shorthand_infers_square_corners() -> None:
    text = "layer trace (0, 2, 2)\n/\\\n\\/\n"
    corrected = correct_vox_shorthand_text(text)
    require(
        f"{BOX_UL}{BOX_UR}\n{BOX_LL}{BOX_LR}\n" in corrected,
        "corner shorthand should infer square corners",
    )


def test_voxtool_corrects_file_in_place() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "shorthand.vox"
        path.write_text(
            "\n".join(
                [
                    "layer trace (0, 2, 2)",
                    "/\\",
                    "\\/",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "correct", str(path)])
        corrected = path.read_text(encoding="utf-8")
    require(exit_code == 0, f"voxtool correct exit: got {exit_code}")
    require(
        f"{BOX_UL}{BOX_UR}\n{BOX_LL}{BOX_LR}" in corrected,
        "voxtool correct should rewrite shorthand corners in place",
    )


def test_voxtool_mirrors_layers_labels_and_trace_notes_to_outfile() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "up-side.vox"
        out_path = Path(tmp_dir) / "pico-side.vox"
        path.write_text(
            "\n".join(
                [
                    "layer base (6, 8, 1)",
                    "LEFT  X*OOXX*X RIGHT",
                    "",
                    "layer trace (6, 8, 1)",
                    "LEFT  .*-...*. RIGHT note .c2=*- .c5 = NET",
                    "",
                    "# trace intents",
                    "# net NET LEFT.c2 RIGHT.c5",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "mirror", str(path), "-out", str(out_path)])
        mirrored = out_path.read_text(encoding="utf-8")
        original = path.read_text(encoding="utf-8")

    expected = "\n".join(
        [
            "layer base (6, 8, 1)",
            "RIGHT X*XXOO*X LEFT",
            "",
            "layer trace (6, 8, 1)",
            "RIGHT .*...-*. LEFT note .c5=-* .c2 = NET",
            "",
            "# trace intents",
            "# net NET RIGHT.c5 LEFT.c2",
            "",
        ]
    )
    require(exit_code == 0, f"voxtool mirror exit: got {exit_code}; {stderr.getvalue()}")
    require(mirrored == expected, f"unexpected mirrored text: {mirrored!r}")
    require("LEFT  .*-...*. RIGHT" in original, "mirror -out should not rewrite the input")


def test_correct_vox_shorthand_preserves_aliases_and_fills_spaces() -> None:
    text = "alias V -> | = VCC\nlayer trace (0, 3, 1)\n V \n"
    corrected = correct_vox_shorthand_text(text)
    require("alias V -> | = VCC\n" in corrected, "alias declaration should be preserved")
    require(".V.\n" in corrected, "correction should fill design-window spaces with dots")


def test_vox2stl_reader_renders_alias_targets() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "alias.vox"
        path.write_text(
            "\n".join(
                [
                    "alias V -> | = VCC",
                    "layer trace (0, 1, 2)",
                    "V",
                    "|",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        layer = vox2stl.read_layers(path)["trace"]
    require(layer.rows == ("|", "|"), "vox2stl reader should render aliases as target glyphs")


def test_vox2stl_reader_ignores_whitespace_only_lines() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "whitespace.vox"
        path.write_text("layer trace (0, 1, 1)\n|\n\t  \n", encoding="utf-8")
        layer = vox2stl.read_layers(path)["trace"]
    require(layer.rows == ("|",), "vox2stl reader should ignore whitespace-only lines")


def test_check_vox_alias_net_assertion_passes_when_connected() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "alias-connected.vox"
        path.write_text(
            "\n".join(
                [
                    "alias V -> | = VCC",
                    "layer trace (3, 5, 4)",
                    "A  ..V..",
                    "B  ..|..",
                    "C  ..|..",
                    "D  ..*..",
                    "",
                    "# trace intents",
                    "# net VCC D.c2",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
    require(exit_code == 0, f"connected alias net exit: got {exit_code}; {stderr.getvalue()}")


def test_check_vox_alias_net_assertion_fails_when_disconnected() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "alias-disconnected.vox"
        path.write_text(
            "\n".join(
                [
                    "alias V -> | = VCC",
                    "layer trace (3, 5, 3)",
                    "A  ..V..",
                    "B  ..O..",
                    "C  ..*..",
                    "",
                    "# trace intents",
                    "# net VCC C.c2",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
        error = stderr.getvalue()
    require(exit_code == 1, f"disconnected alias net exit: got {exit_code}")
    expected = (
        f"error: {path}: net '3V3' component labeled by A.c2 "
        "does not reach any '3V3' pin\n"
    )
    require(error == expected, f"unexpected disconnected alias net error: {error!r}")


def test_check_vox_reports_col_and_alias_net_errors_together() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "multi-error.vox"
        path.write_text(
            "\n".join(
                [
                    "alias V -> | = VCC",
                    "layer trace (3, 5, 3)",
                    "A  ..V..",
                    "B  ..O..",
                    "C  ..*.. note cols c0=|",
                    "",
                    "# trace intents",
                    "# net VCC C.c2",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
        error = stderr.getvalue()
    require(exit_code == 1, f"multi-error alias net exit: got {exit_code}")
    expected = (
        f"error: {path}: trace row 3 (C) c0 (x=-5.08)=|: "
        "column 0 out of design range 1..3\n"
        f"error: {path}: net '3V3' component labeled by A.c2 "
        "does not reach any '3V3' pin\n"
    )
    require(error == expected, f"unexpected multi-error alias net error: {error!r}")


def test_check_vox_accepts_self_consistent_pad_layout_by_file_contents() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "pico2w" / "hat" / "up-side.vox"
        path.parent.mkdir(parents=True)
        path.write_text(
            "\n".join(
                [
                    "layer base (6, 10, 3)",
                    "      XXXXXXXXXX",
                    "GP13  X*XOOOXX*X GP18",
                    "      XXXXXXXXXX",
                    "",
                    "layer trace (6, 10, 3)",
                    "      ..........",
                    "GP13  .*-OOO..*. GP18",
                    "      ..........",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
    require(exit_code == 0, f"self-consistent pad layout exit: got {exit_code}; {stderr.getvalue()}")


def test_check_vox_rejects_stale_pico2w_hat_pin_notes() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "hardware" / "pico2w" / "hat" / "pico-side.vox"
        path.parent.mkdir(parents=True)
        path.write_text(
            "\n".join(
                [
                    "layer trace (6, 10, 5)",
                    "      ..........",
                    "GP18  ....OOO-*. GP13  IR RX target .c6= GP13,.c5 = VCC, .c4 = GND",
                    "GP21  ....OOO-*. GP10  IR TX target .c6= GP10,.c5 = VCC, .c4 = GND",
                    "ADCV  ...OOOO... GP4  AHT20 target .c6 = VCC, .c5 = GND, .c4 = GP5/SCL .c3 = GP4/SDA",
                    "      ..........",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
        error = stderr.getvalue()
    require(exit_code == 1, f"expected stale pin note error, got {exit_code}")
    require("AHT20 target pin note must match pico2w" in error, "missing stale AHT20 pin error")
    require("missing GP28, GP27" in error, "missing expected GP28/GP27 detail")
    require("stale GP4/SDA, GP5/SCL" in error, "missing stale GP4/GP5 detail")


def test_check_vox_accepts_optional_trace_right_pad_with_matching_right_label() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "optional-right-pad.vox"
        path.write_text(
            "\n".join(
                [
                    "layer base (3, 5, 1)",
                    "A  X*X*X RIGHT",
                    "",
                    "layer trace (3, 5, 1)",
                    "A  .*... RIGHT",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
    require(exit_code == 0, f"optional right pad exit: got {exit_code}; {stderr.getvalue()}")


def test_check_vox_warns_trace_pad_mismatch_with_base() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "pad-mismatch.vox"
        path.write_text(
            "\n".join(
                [
                    "layer base (3, 5, 1)",
                    "A  .O*..",
                    "",
                    "layer trace (3, 5, 1)",
                    "A  .*.O.",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
        error = stderr.getvalue()
    require(exit_code == 0, f"pad mismatch warning exit: got {exit_code}; {error}")
    require("expected 'O' from base, got '*'" in error, "checker should warn for mismatched O")
    require("expected 'no pad' from base, got 'O'" in error, "checker should warn for unexpected O")


def test_check_vox_prints_pad_mismatch_warning_with_other_errors() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "pad-warning-with-error.vox"
        path.write_text(
            "\n".join(
                [
                    "layer base (3, 5, 1)",
                    "A  .*...",
                    "",
                    "layer trace (3, 5, 1)",
                    "B  .O...",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
        error = stderr.getvalue()
    require(exit_code == 1, f"expected label error exit, got {exit_code}")
    require("warn pad-warning-with-error.vox" in error, "pad mismatch should remain a warning")
    require("expected '*' from base, got 'O'" in error, "mismatched pad warning should be printed")
    require("error:" in error and "left label 'B' does not match base 'A'" in error, "label error missing")


def test_check_vox_uses_net_notes_without_trace_intents() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "net-note.vox"
        path.write_text(
            "\n".join(
                [
                    "alias V -> | = VCC",
                    "layer trace (6, 5, 3)",
                    "3V3   .*... note .c1=VCC",
                    "B     .|...",
                    "C     .V...",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
    require(exit_code == 0, f"net note without intents exit: got {exit_code}; {stderr.getvalue()}")


def test_check_vox_reports_split_net_notes_without_trace_intents() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "split-net-note.vox"
        path.write_text(
            "\n".join(
                [
                    "alias V -> | = VCC",
                    "layer trace (3, 5, 3)",
                    "A  ..O.. note .c2=VCC",
                    "B  .....",
                    "C  ..V..",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
        error = stderr.getvalue()
    require(exit_code == 1, f"split net note exit: got {exit_code}")
    expected = (
        f"error: {path}: net '3V3' component labeled by A.c2 "
        "does not reach any '3V3' pin\n"
        f"error: {path}: net '3V3' component labeled by C.c2 "
        "does not reach any '3V3' pin\n"
    )
    require(error == expected, f"unexpected split net note error: {error!r}")


def test_check_vox_accepts_vertical_trace_through_leg_pad() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "leg-pad-vertical.vox"
        path.write_text(
            "\n".join(
                [
                    "alias V -> | = VCC",
                    "layer trace (6, 5, 4)",
                    "3V3   .*... note .c1=VCC",
                    "B     .|...",
                    "C     .O... note .c1=VCC",
                    "D     .V...",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
    require(exit_code == 0, f"vertical leg pad exit: got {exit_code}; {stderr.getvalue()}")


def test_check_vox_accepts_horizontal_trace_through_leg_pad() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "leg-pad-horizontal.vox"
        path.write_text(
            "\n".join(
                [
                    "alias V -> - = VCC",
                    "layer trace (6, 5, 1)",
                    "3V3   .*-O. note .c3=VCC",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
    require(exit_code == 0, f"horizontal leg pad exit: got {exit_code}; {stderr.getvalue()}")


def test_check_vox_horizontal_t_junction_truth_table() -> None:
    require(voxtool.horizontal_connects(BOX_T_RIGHT, "-", {}), "BOX_T_RIGHT should connect east")
    require(not voxtool.horizontal_connects("-", BOX_T_RIGHT, {}), "BOX_T_RIGHT should not connect west")
    require(voxtool.horizontal_connects("-", BOX_T_LEFT, {}), "BOX_T_LEFT should connect west")
    require(not voxtool.horizontal_connects(BOX_T_LEFT, "-", {}), "BOX_T_LEFT should not connect east")


def test_check_vox_reports_unanchored_adjacent_same_net_leg_pads() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "adjacent-leg-pads.vox"
        path.write_text(
            "\n".join(
                [
                    "layer trace (3, 5, 1)",
                    "A  .OO.. note .c1=VCC .c2=VCC",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
    require(exit_code == 1, f"adjacent same-net leg pads exit: got {exit_code}")
    expected = (
        f"error: {path}: net '3V3' component labeled by A.c1 "
        "does not reach any '3V3' pin\n"
        f"error: {path}: net '3V3' component labeled by A.c2 "
        "does not reach any '3V3' pin\n"
    )
    require(stderr.getvalue() == expected, f"unexpected adjacent leg pad error: {stderr.getvalue()!r}")



def test_voxtool_check_requires_input_or_all() -> None:
    stderr = io.StringIO()
    try:
        with contextlib.redirect_stderr(stderr):
            voxtool.main(["voxtool.py", "check"])
    except SystemExit as exc:
        exit_code = exc.code
    else:
        exit_code = 0
    require(exit_code == 2, f"voxtool check empty CLI exit: got {exit_code}")
    require("filepath" in stderr.getvalue(), "voxtool check empty CLI should request a filepath")
    require("--all" in stderr.getvalue(), "voxtool check empty CLI should mention --all")


def test_voxtool_stl_writes_ascii_stl() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir) / "straight.stl"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(
                [
                    "voxtool.py",
                    "stl",
                    str(ROOT / "testdata" / "straight.vox"),
                    "--output",
                    str(out_path),
                    "--solid-name",
                    "straight_test",
                ]
            )
        text = out_path.read_text(encoding="ascii")
    require(exit_code == 0, f"voxtool stl exit: got {exit_code}; {stderr.getvalue()}")
    require(text.startswith("solid straight_test\n"), "voxtool STL solid header missing")
    require(text.count("facet normal") > 60, "voxtool STL should include base and holes")


def test_voxtool_stl_writes_full_stl_with_holes() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir) / "straight-full.stl"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(
                [
                    "voxtool.py",
                    "stl",
                    str(ROOT / "testdata" / "straight.vox"),
                    "--output",
                    str(out_path),
                    "--solid-name",
                    "straight_full_test",
                ]
            )
        text = out_path.read_text(encoding="ascii")
    require(exit_code == 0, f"voxtool full stl exit: got {exit_code}; {stderr.getvalue()}")
    require(text.startswith("solid straight_full_test\n"), "voxtool full STL solid header missing")
    require(text.count("facet normal") > 60, "voxtool full STL should include base and holes")


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
    require(text.count("facet normal") > 60, "STL should include base and holes")


def test_cli_writes_full_stl_with_holes() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        out_path = Path(tmp_dir) / "straight-full.stl"
        exit_code = vox2stl.run(
            [
                str(ROOT / "testdata" / "straight.vox"),
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
