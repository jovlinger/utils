#!/usr/bin/env python3
"""Small dependency-free tests for vox2stl."""

from __future__ import annotations

import contextlib
import io
import tempfile
from pathlib import Path
from typing import Sequence

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
        abs(vox2stl.DEFAULT_PIN_OUTSIDE_FRAC - 0.72) < 1e-9,
        "pin outside default should match old trace width",
    )
    require(
        abs(vox2stl.DEFAULT_LEG_OUTSIDE_FRAC - 0.72) < 1e-9,
        "device outside default should match old trace width",
    )
    require(
        abs(vox2stl.DEFAULT_DEVICE_PAD_WIDTH_MM - vox2stl.DEFAULT_PAD_WIDTH_MM) < 1e-9,
        "device pad outer prism should match Pico pad outer prism",
    )
    require(
        abs(vox2stl.DEFAULT_PIN_HOLE_DIAMETER_MM - 1.10 * 0.66) < 1e-9,
        "pin hole default should be 66 percent of the previous Pico hole default",
    )
    require(
        abs(vox2stl.DEFAULT_DEVICE_HOLE_DIAMETER_MM - 1.10) < 1e-9,
        "device hole default should match the previous Pico hole default",
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


def test_check_vox_rejects_trace_pad_mismatch_with_base() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "pad-mismatch.vox"
        path.write_text(
            "\n".join(
                [
                    "layer base (3, 5, 1)",
                    "A  .*O..",
                    "",
                    "layer trace (3, 5, 1)",
                    "A  .*...",
                    "",
                ]
            ),
            encoding="utf-8",
        )
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            exit_code = voxtool.main(["voxtool.py", "check", str(path)])
        error = stderr.getvalue()
    require(exit_code == 1, f"pad mismatch exit: got {exit_code}")
    require("expected 'O' from base, got 'no pad'" in error, "checker should compare pads to base")


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
    require(text.count("facet normal") == 48, "voxtool STL facet count mismatch")


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
                    "--mode",
                    "full",
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
