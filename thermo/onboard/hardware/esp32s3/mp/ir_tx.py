"""IR TX: dry-run on host, esp32.RMT on device.

Canned bootstrap only -- call transmit_mark_space with timings from ir_canned.
"""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import config

# Last dry-run / live TX pulse count (for host tests and /ir responses).
_last_pair_count: int = 0
_last_mode: str = "none"


def last_tx_info() -> Tuple[str, int]:
    return _last_mode, _last_pair_count


def transmit_mark_space(
    pairs: Sequence[Tuple[int, int]],
    *,
    gpio: int = config.IR_TX_GPIO,
    carrier_hz: int = 38_000,
    dry_run: Optional[bool] = None,
) -> int:
    """Transmit (mark_us, space_us) pairs. Returns number of pairs sent."""
    global _last_pair_count, _last_mode
    use_dry: bool = dry_run if dry_run is not None else not _rmt_available()
    if use_dry:
        _last_mode = "dry_run"
        _last_pair_count = len(pairs)
        return _last_pair_count
    _last_mode = "rmt"
    _last_pair_count = _rmt_write(pairs, gpio=gpio, carrier_hz=carrier_hz)
    return _last_pair_count


def _rmt_available() -> bool:
    try:
        import esp32  # noqa: F401
        from machine import Pin  # noqa: F401

        return True
    except ImportError:
        return False


def _rmt_write(
    pairs: Sequence[Tuple[int, int]],
    *,
    gpio: int,
    carrier_hz: int,
) -> int:
    from machine import Pin
    from esp32 import RMT

    # 1 us resolution: APB 80 MHz / clock_div 80.
    pin = Pin(gpio, Pin.OUT)
    rmt = RMT(0, pin=pin, clock_div=80, idle_level=0, tx_carrier=(carrier_hz, 50, 1))
    # write_pulses wants flat duration list in RMT ticks (1 tick ~= 1 us here).
    durations: List[int] = []
    for mark_us, space_us in pairs:
        durations.append(int(mark_us))
        durations.append(int(space_us))
    try:
        rmt.write_pulses(durations, start=1)
    finally:
        try:
            rmt.deinit()
        except AttributeError:
            pass
    return len(pairs)
