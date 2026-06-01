from __future__ import annotations

from common.heatpumpirctl import Fan, Mode, State
from common.heatpumpirctl import HaierYRW02, MideaClassic, profiles


def test_profile_registry_loads_known_dialects() -> None:
    assert profiles.protocol_spec("daikin").name == "daikin_arc452a9"
    assert profiles.protocol_spec("midea").name == "midea_classic"
    assert profiles.protocol_spec("haier").name == "haier_yrw02"
    assert profiles.load_protocol_module("haier_yrw02") is HaierYRW02


def test_midea_classic_state_packet_uses_byte_complements() -> None:
    state = (
        State()
        .set_power(True)
        .set_mode(Mode.COOL)
        .set_temp(22)
        .set_fan(Fan.F1)
    )

    frame = MideaClassic._with_complements(MideaClassic._state_data_bytes(state))

    assert frame == [0xB2, 0x4D, 0x9F, 0x60, 0x70, 0x8F]
    assert MideaClassic.dumps(state).startswith("pulse 4500\nspace 4500\n")


def test_haier_yrw02_state_packet_uses_sum_checksum() -> None:
    state = (
        State()
        .set_power(True)
        .set_mode(Mode.COOL)
        .set_temp(22)
        .set_fan(Fan.F1)
    )

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
        0x4E,
    ]
    assert HaierYRW02.dumps(state).startswith(
        "pulse 3075\nspace 3045\npulse 3085\nspace 4415\n"
    )
