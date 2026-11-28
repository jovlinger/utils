"""Replay captured GPIO edges through the firmware decoder.

The fixtures are serial lines from the board, not a synthetic waveform.
Each test feeds those timestamps and ab pairs, in order, to encoder_on_edge.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware" / "waveshare-knob-touch-lcd-1.8"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "encoder"
REPLAY_SRC = FIRMWARE / "host" / "replay_encoder.cpp"


def _edges(path: Path) -> list[str]:
    lines = [
        line
        for line in path.read_text(encoding="ascii").splitlines()
        if line.startswith("enc us=")
    ]
    if not lines:
        raise AssertionError("no edges in {0}".format(path))
    return lines


def _us(line: str) -> int:
    for tok in line.split():
        if tok.startswith("us="):
            return int(tok.split("=", 1)[1])
    raise AssertionError("no timestamp in {0}".format(line))


def _replay(lines: list[str], tmp_path: Path) -> list[tuple[int, int]]:
    binary = tmp_path / "replay_encoder"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-I",
            str(FIRMWARE / "include"),
            "-o",
            str(binary),
            str(REPLAY_SRC),
        ],
        check=True,
    )
    completed = subprocess.run(
        [str(binary)],
        input="\n".join(lines) + "\n",
        text=True,
        capture_output=True,
        check=True,
    )
    rows: list[tuple[int, int]] = []
    for line in completed.stdout.splitlines():
        step_text, rot_text = line.split()
        rows.append((int(step_text), int(rot_text)))
    assert len(rows) == len(lines)
    return rows


def _steps(rows: list[tuple[int, int]]) -> list[int]:
    return [step for step, _rot in rows if step != 0]


def test_four_positive_detents_count_plus_four(tmp_path: Path) -> None:
    rows = _replay(_edges(FIXTURES / "2026-10-15-four-positive.txt"), tmp_path)
    assert _steps(rows) == [1, 1, 1, 1]
    assert rows[-1][1] == 4


def test_three_negative_detents_count_minus_three(tmp_path: Path) -> None:
    rows = _replay(_edges(FIXTURES / "2026-10-15-three-negative.txt"), tmp_path)
    assert _steps(rows) == [-1, -1, -1]
    assert rows[-1][1] == -3


def test_listen_195059_decodes_each_detent(tmp_path: Path) -> None:
    """The 19:50 serial file. Heartbeats are not edges. The resume marker
    drops the samples between the first run and a later burst."""
    text = (FIXTURES / "2026-10-15-listen-195059.log").read_text(encoding="ascii")
    before, _marker, after = text.partition("--- listen resume")
    first = [line for line in before.splitlines() if line.startswith("enc us=")]
    later = [line for line in after.splitlines() if line.startswith("enc us=")]
    # The resume starts on the tail of a pulse, then the port is idle until
    # the next detent, which begins at ab=3.
    tail = [line for line in later if _us(line) < 200000000]
    burst = [line for line in later if _us(line) >= 200000000]
    assert _steps(_replay(first, tmp_path)) == [1, 1, 1, 1, 1, -1]
    assert _steps(_replay(tail, tmp_path)) == []
    assert _steps(_replay(burst, tmp_path)) == [1, 1, 1, -1, -1]
