#!/usr/bin/env python3
"""Small circuit-validation examples for check_vox."""

from __future__ import annotations

import contextlib
import io
import tempfile
from pathlib import Path
from typing import Iterable

import check_vox


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_check(text: str, name: str = "small-example.vox") -> tuple[int, str, str]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / name
        path.write_text(text, encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = check_vox.main(["check_vox.py", str(path)])
        return exit_code, stdout.getvalue(), stderr.getvalue()


def assert_passes(text: str) -> None:
    exit_code, _, stderr = run_check(text)
    require(exit_code == 0, f"expected pass, got {exit_code}; {stderr}")
    require(stderr == "", f"unexpected stderr: {stderr!r}")


def assert_corrected_passes(text: str) -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "small-example.vox"
        path.write_text(text, encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = check_vox.main(["check_vox.py", "--correct", str(path)])
    require(exit_code == 0, f"expected corrected pass, got {exit_code}; {stderr.getvalue()}")
    require(stderr.getvalue() == "", f"unexpected stderr: {stderr.getvalue()!r}")


def assert_fails_with(text: str, expected_parts: Iterable[str]) -> str:
    exit_code, _, stderr = run_check(text)
    require(exit_code == 1, f"expected failure, got {exit_code}")
    for expected_part in expected_parts:
        require(expected_part in stderr, f"missing {expected_part!r} in {stderr!r}")
    return stderr


def test_check_vox_accepts_matching_pin_labels_with_base() -> None:
    text = "\n".join(
        [
            "layer base (6, 8, 1)",
            "ADCV  X*XXXX*X ADVC",
            "",
            "layer trace (6, 8, 1)",
            "ADCV  .*....*. ADVC",
            "",
        ]
    )
    assert_passes(text)


def test_check_vox_reports_right_label_mismatch_with_base() -> None:
    text = "\n".join(
        [
            "layer base (6, 8, 1)",
            "ADCV  X*XXXX*X ADVC",
            "",
            "layer trace (6, 8, 1)",
            "ADCV  .*....*. GP38",
            "",
        ]
    )
    assert_fails_with(text, ["right label 'GP38' does not match base 'ADVC'"])


def test_check_vox_reports_wrong_horizontal_t_for_gnd_left_and_right() -> None:
    gnd_left_wrong = "\n".join(
        [
            "alias G -> | = GND",
            "",
            "layer trace (6, 8, 2)",
            "GND   .*->....",
            "A     ...G....",
            "",
        ]
    )
    assert_fails_with(
        gnd_left_wrong,
        ["net 'GND' component labeled by A.c3"],
    )

    gnd_right_wrong = "\n".join(
        [
            "alias G -> | = GND",
            "",
            "layer trace (6, 8, 2)",
            "SRC   ....<-*. GND",
            "A     ....G...",
            "",
        ]
    )
    assert_fails_with(
        gnd_right_wrong,
        ["net 'GND' component labeled by A.c4"],
    )


def test_check_vox_reports_wrong_horizontal_t_for_vcc_left_and_right() -> None:
    vcc_left_wrong = "\n".join(
        [
            "alias V -> | = VCC",
            "",
            "layer trace (6, 8, 2)",
            "3V3   .*->....",
            "A     ...V....",
            "",
        ]
    )
    assert_fails_with(
        vcc_left_wrong,
        ["net '3V3' component labeled by A.c3"],
    )

    vcc_right_wrong = "\n".join(
        [
            "alias V -> | = VCC",
            "",
            "layer trace (6, 8, 2)",
            "SRC   ....<-*. 3V3",
            "A     ....V...",
            "",
        ]
    )
    assert_fails_with(
        vcc_right_wrong,
        ["net '3V3' component labeled by A.c4"],
    )


def test_check_vox_reports_wrong_vertical_t_for_gnd_and_vcc() -> None:
    gnd_above_wrong = "\n".join(
        [
            "alias G -> | = GND",
            "",
            "layer trace (6, 8, 2)",
            "A     ...G....",
            "GND   .*-T....",
            "",
        ]
    )
    assert_fails_with(
        gnd_above_wrong,
        ["net 'GND' component labeled by A.c3"],
    )

    vcc_below_wrong = "\n".join(
        [
            "alias V -> | = VCC",
            "",
            "layer trace (6, 8, 2)",
            "3V3   .*-^....",
            "A     ...V....",
            "",
        ]
    )
    assert_fails_with(
        vcc_below_wrong,
        ["net '3V3' component labeled by A.c3"],
    )

    assert_fails_with(
        "\n".join(
            [
                "alias Q -> | = GP19",
                "",
                "layer trace (6, 8, 2)",
                "GP19  .*--....",
                "A     ...Q--..",
                "",
            ]
        ),
        ["net 'GP19' component labeled by A.c3"],
    )



def test_check_vox_accepts_correct_alias_t_junctions() -> None:
    assert_passes(
        "\n".join(
            [
                "alias G -> | = GND",
                "",
                "layer trace (6, 8, 2)",
                "GND   .*-<....",
                "A     ...G....",
                "",
            ]
        )
    )
    assert_passes(
        "\n".join(
            [
                "alias G -> | = GND",
                "",
                "layer trace (6, 8, 2)",
                "SRC   ....>-*. GND",
                "A     ....G...",
                "",
            ]
        )
    )
    assert_passes(
        "\n".join(
            [
                "alias V -> | = VCC",
                "",
                "layer trace (6, 8, 2)",
                "3V3   .*-<....",
                "A     ...V....",
                "",
            ]
        )
    )
    assert_passes(
        "\n".join(
            [
                "alias V -> | = VCC",
                "",
                "layer trace (6, 8, 2)",
                "SRC   ....>-*. 3V3",
                "A     ....V...",
                "",
            ]
        )
    )
    assert_passes(
        "\n".join(
            [
                "alias G -> | = GND",
                "",
                "layer trace (6, 8, 2)",
                "A     ...G....",
                "GND   .*-^....",
                "",
            ]
        )
    )
    assert_passes(
        "\n".join(
            [
                "alias V -> | = VCC",
                "",
                "layer trace (6, 8, 2)",
                "3V3   .*-T....",
                "A     ...V....",
                "",
            ]
        )
    )
    assert_passes(
        "\n".join(
            [
                "alias Q -> | = GP19",
                "",
                "layer trace (6, 8, 2)",
                "GP19  .*-+....",
                "A     ...Q....",
                "",
            ]
        )
    )
    assert_passes(
        "\n".join(
            [
                "alias V -> | = VCC",
                "",
                "layer trace (6, 8, 2)",
                "3V3   .*-O....",
                "A     ...V....",
                "",
            ]
        )
    )
    assert_passes(
        "\n".join(
            [
                "alias V -> | = VCC",
                "",
                "layer trace (6, 8, 2)",
                "3V3   .*-*....",
                "A     ...V....",
                "",
            ]
        )
    )
    assert_corrected_passes(
        "\n".join(
            [
                "alias G -> | = GND",
                "",
                "layer trace (6, 8, 2)",
                "A     ...G....",
                "GND   .*-/....",
                "",
            ]
        )
    )
    assert_corrected_passes(
        "\n".join(
            [
                "alias V -> | = VCC",
                "",
                "layer trace (6, 8, 2)",
                "3V3   .*-\\....",
                "A     ...V....",
                "",
            ]
        )
    )


def test_check_vox_aht20_left_feed_connects_vcc_then_gnd_then_scl_then_sda() -> None:
    only_vcc_connected = "\n".join(
        [
            "layer trace (6, 8, 4)",
            "3V3   .*-O.... note .c3 = VCC",
            "GND   .*.O.... note .c3 = GND",
            "GP28  .*.O.... note .c3 = GP28",
            "GP35  .*.O.... note .c3 = GP35",
            "",
        ]
    )
    assert_fails_with(
        only_vcc_connected,
        [
            "net 'GND' component labeled by GND.c3",
            "net 'GP28' component labeled by GP28.c3",
            "net 'GP35' component labeled by GP35.c3",
        ],
    )

    vcc_and_gnd_connected = "\n".join(
        [
            "layer trace (6, 8, 4)",
            "3V3   .*-O.... note .c3 = VCC",
            "GND   .*-O.... note .c3 = GND",
            "GP28  .*.O.... note .c3 = GP28",
            "GP35  .*.O.... note .c3 = GP35",
            "",
        ]
    )
    assert_fails_with(
        vcc_and_gnd_connected,
        [
            "net 'GP28' component labeled by GP28.c3",
            "net 'GP35' component labeled by GP35.c3",
        ],
    )

    vcc_gnd_scl_connected = "\n".join(
        [
            "layer trace (6, 8, 4)",
            "3V3   .*-O.... note .c3 = VCC",
            "GND   .*-O.... note .c3 = GND",
            "GP28  .*-O.... note .c3 = GP28",
            "GP35  .*.O.... note .c3 = GP35",
            "",
        ]
    )
    assert_fails_with(
        vcc_gnd_scl_connected,
        ["net 'GP35' component labeled by GP35.c3"],
    )

    all_connected = "\n".join(
        [
            "layer trace (6, 8, 4)",
            "3V3   .*-O.... note .c3 = VCC",
            "GND   .*-O.... note .c3 = GND",
            "GP28  .*-O.... note .c3 = GP28",
            "GP35  .*-O.... note .c3 = GP35",
            "",
        ]
    )
    assert_passes(all_connected)

    sda_routed_to_wrong_pin = "\n".join(
        [
            "layer trace (6, 8, 4)",
            "3V3   .*-O.... note .c3 = VCC",
            "GND   .*-O.... note .c3 = GND",
            "GP28  .*-O.... note .c3 = GP28",
            "GP36  .*-O.... note .c3 = GP35",
            "",
        ]
    )
    assert_fails_with(
        sda_routed_to_wrong_pin,
        ["conflicting net labels", "GP35 from GP36.c3", "GP36 from GP36:1.c1"],
    )


def test_check_vox_aht20_right_feed_connects_all_vertical_mount_legs() -> None:
    all_connected = "\n".join(
        [
            "layer trace (6, 8, 4)",
            "A1    ....O-*. 3V3 note .c4 = VCC",
            "A2    ....O-*. GND note .c4 = GND",
            "A3    ....O-*. GP28 note .c4 = GP28",
            "A4    ....O-*. GP35 note .c4 = GP35",
            "",
        ]
    )
    assert_passes(all_connected)

    sda_unconnected = "\n".join(
        [
            "layer trace (6, 8, 4)",
            "A1    ....O-*. 3V3 note .c4 = VCC",
            "A2    ....O-*. GND note .c4 = GND",
            "A3    ....O-*. GP28 note .c4 = GP28",
            "A4    ....O.*. GP35 note .c4 = GP35",
            "",
        ]
    )
    assert_fails_with(
        sda_unconnected,
        ["net 'GP35' component labeled by A4.c4"],
    )

    sda_routed_to_wrong_pin = "\n".join(
        [
            "layer trace (6, 8, 4)",
            "A1    ....O-*. 3V3 note .c4 = VCC",
            "A2    ....O-*. GND note .c4 = GND",
            "A3    ....O-*. GP28 note .c4 = GP28",
            "A4    ....O-*. GP36 note .c4 = GP35",
            "",
        ]
    )
    assert_fails_with(
        sda_routed_to_wrong_pin,
        ["conflicting net labels", "GP35 from A4.c4", "GP36 from GP36:1.c6"],
    )


def main() -> int:
    test_check_vox_accepts_matching_pin_labels_with_base()
    test_check_vox_reports_right_label_mismatch_with_base()
    test_check_vox_reports_wrong_horizontal_t_for_gnd_left_and_right()
    test_check_vox_reports_wrong_horizontal_t_for_vcc_left_and_right()
    test_check_vox_reports_wrong_vertical_t_for_gnd_and_vcc()
    test_check_vox_accepts_correct_alias_t_junctions()
    test_check_vox_aht20_left_feed_connects_vcc_then_gnd_then_scl_then_sda()
    test_check_vox_aht20_right_feed_connects_all_vertical_mount_legs()
    print("ok check_vox small examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
