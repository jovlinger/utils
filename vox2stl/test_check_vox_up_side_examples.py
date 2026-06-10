#!/usr/bin/env python3
"""Complete up-side fixture tests for check_vox."""

from __future__ import annotations

import contextlib
import io
import tempfile
from pathlib import Path

import check_vox


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def run_check(vox_text: str, *, correct: bool = False) -> tuple[int, str, str, str]:
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "up-side-current-trace.vox"
        path.write_text(vox_text, encoding="utf-8")
        stdout = io.StringIO()
        stderr = io.StringIO()
        argv = ["check_vox.py"]
        if correct:
            argv.append("--correct")
        argv.append(str(path))
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            exit_code = check_vox.main(argv)
        corrected = path.read_text(encoding="utf-8")
        return exit_code, stdout.getvalue(), stderr.getvalue(), corrected


def test_check_vox_current_up_side_trace_fixture_reports_floating_nets() -> None:
    text = "\n".join(
        [
            "alias V -> | = VCC",
            "alias G -> | = GND",
            "",
            "layer trace (6, 10, 22)",
            "      ..........",
            "GP15  .*..up..*. GP16",
            "GP14  .*.side.*. GP17",
            "GND   .*......*. GND",
            "GP13  .*-OOO..*. GP18  IR RX target .c3= GP13,.c4 = VCC, .c5 = GND",
            "GP12  .*..||..*. GP19",
            "GP11  .*..||..*. GP20",
            "GP10  .*-OOO..*. GP21  IR TX target .c3= GP10,.c4 = VCC, .c5 = GND",
            "GND   .*..|<--*. GND",
            "GP9   .*..V|..*. GP22",
            "GP8   .*..|G..*. RUN",
            "GP7   .*..||..*. GP26",
            "GP6   .*.┌┘|..*. GP27",
            "GND   .*.|┌┘..*. GND",
            "GP5   .*.||┌--*. GP28  SCL",
            "GP4   .*.OOOO.*. GP38  AHT20 target .c3 = VCC, .c4 = GND, .c5 = GP28 (SCL) .c6 = GP35 (SDA); big 7-pin keepout",
            "GP3   .*.\\----*. 3V3",
            "GP2   .*......*. 3EN",
            "GND   .*......*. GND",
            "GP1   .*......*. VSYS",
            "GP0   .*..usb.*. VBUS",
            "      ..........",
            "",
        ]
    )
    exit_code, _, stderr, _ = run_check(text)
    require(exit_code == 1, f"current up-side trace fixture should fail, got {exit_code}")
    require("net '3V3' component labeled by" in stderr and "GP9.c4" in stderr, "3V3 floating error missing")
    require("net 'GND' component labeled by" in stderr and "GP8.c5" in stderr, "GND floating error missing")
    require("net 'GP35' component labeled by GP4.c6" in stderr, "GP35 floating error missing")


def test_check_vox_current_up_side_trace_fixture_passes_right_label() -> None:
    text = "\n".join(
        [
            "alias V -> | = VCC",
            "alias G -> | = GND",
            "",
            "layer trace (6, 10, 22)",
            "      ..........",
            "GP15  .*..up..*. GP16",
            "GP14  .*.side.*. GP17",
            "GND   .*......*. GND",
            "GP13  .*-OOO..*. GP18  IR RX target .c3= GP13,.c4 = VCC, .c5 = GND",
            "GP12  .*..||..*. GP19",
            "GP11  .*..||..*. GP20",
            "GP10  .*-OOO..*. GP21  IR TX target .c3= GP10,.c4 = VCC, .c5 = GND",
            "GND   .*..|>--*. GND",
            "GP9   .*..V|..*. GP22",
            "GP8   .*..|G..*. RUN",
            "GP7   .*..||..*. GP26",
            "GP6   .*.┌┘|..*. GP27",
            "GND   .*.|┌┘..*. GND",
            "GP5   .*.||┌--*. GP28  SCL",
            "GP4   .*.OOOO.*. ADCV  AHT20 target .c3 = VCC, .c4 = GND, .c5 = GP28 (SCL); big 7-pin keepout",
            "GP3   .*.└----*. 3V3",
            "GP2   .*......*. 3EN",
            "GND   .*......*. GND",
            "GP1   .*......*. VSYS",
            "GP0   .*..usb.*. VBUS",
            "      ..........",
            "",
        ]
    )
    exit_code, _, stderr, _ = run_check(text)
    require(exit_code == 0, f"current up-side trace fixture should pass, got {exit_code}; {stderr}")
    require(stderr == "", f"unexpected up-side error: {stderr!r}")


def test_check_vox_corrects_current_up_side_trace_fixture_before_validation() -> None:
    before_text = "\n".join(
        [
            "alias V -> | = VCC",
            "alias G -> | = GND",
            "",
            "layer trace (6, 10, 22)",
            "      ..........",
            "GP15  .*..up..*. GP16",
            "GP14  .*.side.*. GP17",
            "GND   .*......*. GND",
            "GP13  .*-OOO..*. GP18  IR RX target .c3= GP13,.c4 = VCC, .c5 = GND",
            "GP12  .*..||..*. GP19",
            "GP11  .*..||..*. GP20",
            "GP10  .*-OOO..*. GP21  IR TX target .c3= GP10,.c4 = VCC, .c5 = GND",
            "GND   .*..|<--*. GND",
            "GP9   .*..V|..*. GP22",
            "GP8   .*..|G..*. RUN",
            "GP7   .*..||..*. GP26",
            "GP6   .*.┌┘|..*. GP27",
            "GND   .*.|┌┘..*. GND",
            "GP5   .*.||┌--*. GP28  SCL",
            "GP4   .*.OOOO.*. ADCV  AHT20 target .c3 = VCC, .c4 = GND, .c5 = GP28 (SCL) .c6 = GP35 (SDA); big 7-pin keepout",
            "GP3   .*.\\----*. 3V3",
            "GP2   .*......*. 3EN",
            "GND   .*......*. GND",
            "GP1   .*......*. VSYS",
            "GP0   .*..usb.*. VBUS",
            "      ..........",
            "",
        ]
    )
    after_text = "\n".join(
        [
            "alias V -> | = VCC",
            "alias G -> | = GND",
            "",
            "layer trace (6, 10, 22)",
            "      ..........",
            "GP15  .*..up..*. GP16",
            "GP14  .*.side.*. GP17",
            "GND   .*......*. GND",
            "GP13  .*-OOO..*. GP18  IR RX target .c3= GP13,.c4 = VCC, .c5 = GND",
            "GP12  .*..||..*. GP19",
            "GP11  .*..||..*. GP20",
            "GP10  .*-OOO..*. GP21  IR TX target .c3= GP10,.c4 = VCC, .c5 = GND",
            "GND   .*..|┤--*. GND",
            "GP9   .*..V|..*. GP22",
            "GP8   .*..|G..*. RUN",
            "GP7   .*..||..*. GP26",
            "GP6   .*.┌┘|..*. GP27",
            "GND   .*.|┌┘..*. GND",
            "GP5   .*.||┌--*. GP28  SCL",
            "GP4   .*.OOOO.*. ADCV  AHT20 target .c3 = VCC, .c4 = GND, .c5 = GP28 (SCL) .c6 = GP35 (SDA); big 7-pin keepout",
            "GP3   .*.└----*. 3V3",
            "GP2   .*......*. 3EN",
            "GND   .*......*. GND",
            "GP1   .*......*. VSYS",
            "GP0   .*..usb.*. VBUS",
            "      ..........",
            "",
        ]
    )
    exit_code, stdout, stderr, corrected = run_check(before_text, correct=True)
    require(corrected == after_text, f"unexpected corrected up-side text: {corrected!r}")
    require(exit_code == 1, f"corrected up-side trace fixture should fail, got {exit_code}")
    require(stdout == "", f"unexpected up-side stdout: {stdout!r}")
    require("net 'GND' component labeled by" in stderr and "GP8.c5" in stderr, "GND floating error missing")
    require("net 'GP35' component labeled by GP4.c6" in stderr, "GP35 floating error missing")


def test_check_vox_current_up_side_trace_fixture_fails_on_right_label_with_sda_trace() -> None:
    text = "\n".join(
        [
            "alias V -> | = VCC",
            "alias G -> | = GND",
            "",
            "layer trace (6, 10, 22)",
            "      ..........",
            "GP15  .*..up..*. GP16",
            "GP14  .*.side.*. GP17",
            "GND   .*......*. GND",
            "GP13  .*-OOO..*. GP18  IR RX target .c3= GP13,.c4 = VCC, .c5 = GND",
            "GP12  .*..||..*. GP19",
            "GP11  .*..||..*. GP20",
            "GP10  .*-OOO..*. GP21  IR TX target .c3= GP10,.c4 = VCC, .c5 = GND",
            "GND   .*..|<--*. GND",
            "GP9   .*..V|..*. GP22",
            "GP8   .*..|G..*. RUN",
            "GP7   .*..||..*. GP26",
            "GP6   .*.┌┘|..*. GP27",
            "GND   .*.|┌┘..*. GND",
            "GP5   .*.||┌--*. GP28  SCL",
            "GP4   .*.OOOO-*. ADCV  AHT20 target .c3 = VCC, .c4 = GND, .c5 = GP28 (SCL) .c6 = GP35 (SDA); big 7-pin keepout",
            "GP3   .*.\\----*. 3V3",
            "GP2   .*......*. 3EN",
            "GND   .*......*. GND",
            "GP1   .*......*. VSYS",
            "GP0   .*..usb.*. VBUS",
            "      ..........",
            "",
        ]
    )
    exit_code, _, stderr, _ = run_check(text)
    require(exit_code == 1, f"current up-side trace fixture should fail, got {exit_code}")
    require("net '3V3' component labeled by" in stderr and "GP9.c4" in stderr, "3V3 floating error missing")
    require("net 'GND' component labeled by" in stderr and "GP8.c5" in stderr, "GND floating error missing")


def test_check_vox_current_up_side_trace_after_right_label_fails_unconnected() -> None:
    text = "\n".join(
        [
            "alias V -> | = VCC",
            "alias G -> | = GND",
            "",
            "layer trace (6, 10, 22)",
            "      ..........",
            "GP15  .*..up..*. GP16",
            "GP14  .*.side.*. GP17",
            "GND   .*......*. GND",
            "GP13  .*-OOO..*. GP18  IR RX target .c3= GP13,.c4 = VCC, .c5 = GND",
            "GP12  .*..||..*. GP19",
            "GP11  .*..||..*. GP20",
            "GP10  .*-OOO..*. GP21  IR TX target .c3= GP10,.c4 = VCC, .c5 = GND",
            "GND   .*..|>--*. GND",
            "GP9   .*..V|..*. GP22",
            "GP8   .*..|G..*. RUN",
            "GP7   .*..||..*. GP26",
            "GP6   .*.┌┘|..*. GP27",
            "GND   .*.|┌┘..*. GND",
            "GP5   .*.||┌--*. GP28  SCL",
            "GP4   .*.OOOO-*. ADCV  AHT20 target .c3 = VCC, .c4 = GND, .c5 = GP28 (SCL) .c6 = GP35 (SDA); big 7-pin keepout",
            "GP3   .*......*. 3V3",
            "GP2   .*......*. 3EN",
            "GND   .*......*. GND",
            "GP1   .*......*. VSYS",
            "GP0   .*..usb.*. VBUS",
            "      ..........",
            "",
        ]
    )
    exit_code, _, stderr, _ = run_check(text)
    require(exit_code == 1, f"up-side trace after right label fix should fail, got {exit_code}")
    require("net '3V3' component labeled by" in stderr and "GP9.c4" in stderr, "3V3 floating error missing")


def test_check_vox_current_up_side_trace_fixture_fails_on_label_mismatch() -> None:
    text = "\n".join(
        [
            "alias V -> | = VCC",
            "alias G -> | = GND",
            "",
            "layer trace (6, 10, 22)",
            "      ..........",
            "GP15  .*..up..*. GP16",
            "GP14  .*.side.*. GP17",
            "GND   .*......*. GND",
            "GP13  .*-OOO..*. GP18  IR RX target .c3= GP13,.c4 = VCC, .c5 = GND",
            "GP12  .*..||..*. GP19",
            "GP11  .*..||..*. GP20",
            "GP10  .*-OOO..*. GP21  IR TX target .c3= GP10,.c4 = VCC, .c5 = GND",
            "GND   .*..|<--*. GND",
            "GP9   .*..G|..*. GP22",
            "GP8   .*..|V..*. RUN",
            "GP7   .*..||..*. GP26",
            "GP6   .*.┌┘|..*. GP27",
            "GND   .*.|┌┘..*. GND",
            "GP5   .*.||┌--*. GP28  SCL",
            "GP4   .*.OOOO.*. ADCV  AHT20 target .c3 = VCC, .c4 = GND, .c5 = GP28 (SCL) .c6 = GP35 (SDA); big 7-pin keepout",
            "GP3   .*.\\----*. 3V3",
            "GP2   .*......*. 3EN",
            "GND   .*......*. GND",
            "GP1   .*......*. VSYS",
            "GP0   .*..usb.*. VBUS",
            "      ..........",
            "",
        ]
    )
    exit_code, _, stderr, _ = run_check(text)
    require(exit_code == 1, f"current up-side trace fixture should fail, got {exit_code}")
    require("conflicting net labels: 3V3 from" in stderr and "GND from GP9.c4" in stderr, "GND mismatch error missing")
    require("3V3 from GP8.c5, GND from" in stderr, "3V3 mismatch error missing")
    require("net 'GP35' component labeled by GP4.c6" in stderr, "GP35 floating error missing")


def test_check_vox_current_up_side_trace_fixture_fails_on_floating_power_and_ground() -> None:
    text = "\n".join(
        [
            "alias V -> | = VCC",
            "alias G -> | = GND",
            "",
            "layer trace (6, 10, 22)",
            "      ..........",
            "GP15  .*..up..*. GP16",
            "GP14  .*.side.*. GP17",
            "GND   .*......*. GND",
            "GP13  .*-OOO..*. GP18  IR RX target .c3= GP13,.c4 = VCC, .c5 = GND",
            "GP12  .*..||..*. GP19",
            "GP11  .*..||..*. GP20",
            "GP10  .*-OOO..*. GP21  IR TX target .c3= GP10,.c4 = VCC, .c5 = GND",
            "GND   .*..|<--*. GND",
            "GP9   .*..V|..*. GP22",
            "GP8   .*..|G..*. RUN",
            "GP7   .*..||..*. GP26",
            "GP6   .*.┌┘|..*. GP27",
            "GND   .*.|┌┘..*. GND",
            "GP5   .*.||┌--*. GP28  SCL",
            "GP4   .*.OOOO.*. ADCV  AHT20 target .c3 = VCC, .c4 = GND, .c5 = GP28 (SCL) .c6 = GP35 (SDA); big 7-pin keepout",
            "GP3   .*.\\----*. 3V3",
            "GP2   .*......*. 3EN",
            "GND   .*......*. GND",
            "GP1   .*......*. VSYS",
            "GP0   .*..usb.*. VBUS",
            "      ..........",
            "",
        ]
    )
    exit_code, _, stderr, _ = run_check(text)
    require(exit_code == 1, f"current up-side trace fixture should fail, got {exit_code}")
    require("net '3V3' component labeled by" in stderr and "GP9.c4" in stderr, "3V3 floating error missing")
    require("net 'GND' component labeled by" in stderr and "GP8.c5" in stderr, "GND floating error missing")
    require("net 'GP35' component labeled by GP4.c6" in stderr, "GP35 floating error missing")


def main() -> int:
    test_check_vox_current_up_side_trace_fixture_reports_floating_nets()
    test_check_vox_current_up_side_trace_fixture_passes_right_label()
    test_check_vox_corrects_current_up_side_trace_fixture_before_validation()
    test_check_vox_current_up_side_trace_fixture_fails_on_right_label_with_sda_trace()
    test_check_vox_current_up_side_trace_after_right_label_fails_unconnected()
    test_check_vox_current_up_side_trace_fixture_fails_on_label_mismatch()
    test_check_vox_current_up_side_trace_fixture_fails_on_floating_power_and_ground()
    print("ok check_vox up-side examples")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
