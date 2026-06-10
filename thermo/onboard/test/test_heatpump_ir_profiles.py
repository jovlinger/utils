from __future__ import annotations

from common.heatpumpirctl import Fan, Mode, State
from common.heatpumpirctl import HaierYRW02, MideaClassic, profiles


def _mode2_frames(mode2: str) -> list[list[int]]:
    frames: list[list[int]] = []
    bits: list[int] = []
    in_frame = False
    expect_bit_space = False

    for line in mode2.splitlines():
        kind, value_text = line.split()
        value = int(value_text)
        if kind == "pulse" and value == MideaClassic.START_PULSE_US:
            if in_frame:
                frames.append(_bits_to_bytes(bits))
            bits = []
            in_frame = True
            expect_bit_space = False
        elif in_frame and kind == "pulse" and value == MideaClassic.PULSE_US:
            expect_bit_space = True
        elif in_frame and kind == "space" and expect_bit_space:
            if value == MideaClassic.GAP_US:
                frames.append(_bits_to_bytes(bits))
                in_frame = False
                bits = []
            else:
                bits.append(1 if value == MideaClassic.SPACE_ONE_US else 0)
            expect_bit_space = False

    if in_frame:
        frames.append(_bits_to_bytes(bits))
    return frames


def _bits_to_bytes(bits: list[int]) -> list[int]:
    frame: list[int] = []
    for start in range(0, len(bits), 8):
        byte = 0
        for bit in bits[start : start + 8]:
            byte = (byte << 1) | bit
        frame.append(byte)
    return frame


def test_profile_registry_loads_known_dialects() -> None:
    assert profiles.protocol_spec("daikin").name == "daikin_arc452a9"
    assert profiles.protocol_spec("midea").name == "midea_classic"
    assert profiles.protocol_spec("haier").name == "haier_yrw02"
    assert profiles.load_protocol_module("haier_yrw02") is HaierYRW02


def test_midea_classic_state_packet_uses_byte_complements() -> None:
    state = State().set_power(True).set_mode(Mode.COOL).set_temp(22).set_fan(Fan.F1)

    frame = MideaClassic._with_complements(MideaClassic._state_data_bytes(state))

    assert frame == [0xB2, 0x4D, 0x9F, 0x60, 0x70, 0x8F]
    assert MideaClassic.dumps(state).startswith("pulse 4500\nspace 4500\n")


def test_midea_classic_powered_on_sequence_includes_office_secondary_frame() -> None:
    state = State().set_power(True).set_mode(Mode.COOL).set_temp(22).set_fan(Fan.F1)

    assert _mode2_frames(MideaClassic.dumps(state)) == [
        [0xB2, 0x4D, 0x9F, 0x60, 0x70, 0x8F],
        [0xB2, 0x4D, 0x9F, 0x60, 0x70, 0x8F],
        [0xD5, 0x28, 0x00, 0x01, 0x00, 0xFE],
    ]


def test_midea_classic_power_off_keeps_two_state_packets() -> None:
    state = State().set_power(False).set_mode(Mode.COOL).set_temp(22).set_fan(Fan.F1)

    assert _mode2_frames(MideaClassic.dumps(state)) == [
        [0xB2, 0x4D, 0x7B, 0x84, 0xE0, 0x1F],
        [0xB2, 0x4D, 0x7B, 0x84, 0xE0, 0x1F],
    ]


def test_haier_yrw02_state_packet_uses_sum_checksum() -> None:
    state = State().set_power(True).set_mode(Mode.COOL).set_temp(22).set_fan(Fan.F1)

    frame = HaierYRW02._state_bytes(state)

    assert frame == [
        0xA6,
        0x62,
        0x00,
        0x00,
        0x40,
        0x60,
        0x00,
        0x20,
        0x00,
        0x00,
        0x20,
        0x00,
        0x06,
        0xEE,
    ]
    assert HaierYRW02.dumps(state).startswith(
        "pulse 3075\nspace 3045\npulse 3085\nspace 4415\n"
    )
