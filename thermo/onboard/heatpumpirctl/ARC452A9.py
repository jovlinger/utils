"""Daikin ARC452A9 protocol: encode/decode between State and ir-ctl bytes.

ARC452A9 sends 2 frames per keypress:
  F1 (8 bytes): fixed header ``11 da 27 f0 00 00 00 02``
  F3 (19 bytes): full unit state (mode, temp, fan, timers, etc.)
No Frame 2 (0x42) is sent (unlike the ARC470A1 / blafois 3-frame protocol).
Inter-frame gap: ~30 ms.  Encoding: pulse-distance, 38 kHz, LSB-first.

Public API
----------
load(f3_bytes, f1_bytes?) -> State   Decode F3 (and optional F1) into State.
dump(state)              -> (f1, f3)  Encode State into (F1 bytes, F3 bytes).
loads(ir_text)            -> State   Parse ir-ctl output; first F1+F3 only.
dumps(state)              -> str     Encode State into ir-ctl mode2 text.
iter_frames(ir_text)      -> (kind, raw_bytes)  Every frame in order.
decode_segment(pairs)     -> [(kind, raw_bytes)]  Frames in one gap-bounded segment.
iter_events(line)         -> (kind, us)  Parse one line of ir-ctl mode2 (pulse/space/timeout).
"""

from __future__ import annotations

import re
from typing import Iterator, List, Optional, Sequence, Tuple

from . import Fan, Mode, State

# ---------------------------------------------------------------------------
# Timing constants (microseconds)
# ---------------------------------------------------------------------------

PULSE_US = 430
SPACE_ZERO_US = 420
SPACE_ONE_US = 1320
START_PULSE_US = 3400
START_SPACE_US = 1750
GAP_US = 30_000

# Decode thresholds
PULSE_MIN, PULSE_MAX = 250, 650
SPACE_ZERO_MIN, SPACE_ZERO_MAX = 300, 550
SPACE_ONE_MIN, SPACE_ONE_MAX = 1000, 1600
GAP_MIN = 5_000

# ---------------------------------------------------------------------------
# Fixed F1 frame for ARC452A9
# ---------------------------------------------------------------------------

F1_FIXED = [0x11, 0xDA, 0x27, 0xF0, 0x00, 0x00, 0x00, 0x02]

HEADER = [0x11, 0xDA, 0x27]

# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------

_MODE_TO_NIB = {m: m.value for m in Mode}
_NIB_TO_MODE = {m.value: m for m in Mode}
_FAN_TO_NIB = {f: f.value for f in Fan}
_NIB_TO_FAN = {f.value: f for f in Fan}

# ---------------------------------------------------------------------------
# Checksum
# ---------------------------------------------------------------------------


def _checksum(data: Sequence[int]) -> int:
    return sum(data) & 0xFF


def _checksum_ok(frame: Sequence[int]) -> bool:
    if len(frame) < 2:
        return False
    return frame[-1] == _checksum(frame[:-1])


# ---------------------------------------------------------------------------
# Byte-level encode / decode  (State <-> frame bytes)
# ---------------------------------------------------------------------------


def dump(state: State) -> Tuple[List[int], List[int]]:
    """Encode State into (F1 bytes, F3 bytes) for the ARC452A9."""
    f1 = list(F1_FIXED)

    byte5 = (_MODE_TO_NIB.get(state.mode, 0) << 4) | (0x01 if state.power else 0x00)
    if state.timer_off_minutes is not None:
        byte5 |= 0x02
    if state.timer_on_minutes is not None:
        byte5 |= 0x04

    temp_byte = max(20, min(64, state.half_c))
    fan_byte = (_FAN_TO_NIB.get(state.fan, 0xA) << 4) | (0x0F if state.swing else 0x00)

    timer_on_min = state.timer_on_minutes or 0
    timer_off_min = state.timer_off_minutes or 0
    timer_a = timer_on_min & 0xFF
    timer_b = ((timer_on_min >> 8) & 0x0F) | ((timer_off_min & 0x0F) << 4)
    timer_c = (timer_off_min >> 4) & 0xFF

    body = [
        0x11,
        0xDA,
        0x27,
        0x00,
        0x00,
        byte5,
        temp_byte,
        0x00,
        fan_byte,
        0x00,
        timer_a,
        timer_b,
        timer_c,
        0x01 if state.powerful else 0x00,
        0x00,
        0xC0,
        0x04 if state.econo else 0x00,
        0x00,
    ]
    body.append(_checksum(body))
    return f1, body


def load(f3: Sequence[int], f1: Optional[Sequence[int]] = None) -> State:
    """Decode F3 (and optionally F1) byte list into State."""
    s = State()
    s.raw_f3 = list(f3)
    if f1 is not None:
        s.raw_f1 = list(f1)

    n = len(f3)
    if n < 19:
        s.truncated = True
    if not _checksum_ok(f3) and n >= 19:
        s.truncated = True

    if n > 5:
        b5 = f3[5]
        s.power = bool(b5 & 0x01)
        nib = (b5 >> 4) & 0x0F
        s.mode = _NIB_TO_MODE.get(nib, Mode.AUTO)

    if n > 6:
        s.half_c = f3[6]

    if n > 8:
        fan_nib = (f3[8] >> 4) & 0x0F
        s.fan = _NIB_TO_FAN.get(fan_nib, Fan.AUTO)
        s.swing = (f3[8] & 0x0F) == 0x0F

    if n > 0x0C:
        b5 = f3[5]
        if b5 & 0x04:
            s.timer_on_minutes = ((f3[0x0B] & 0x0F) << 8) | f3[0x0A]
        if b5 & 0x02:
            s.timer_off_minutes = (f3[0x0C] << 4) | (f3[0x0B] >> 4)

    if n > 0x0D:
        s.powerful = bool(f3[0x0D] & 0x01)

    if n > 0x10:
        s.econo = bool(f3[0x10] & 0x04)

    if f1 is not None and len(f1) > 6:
        s.comfort = bool(f1[6] & 0x10)

    return s


# ---------------------------------------------------------------------------
# IR pulse-train encode / decode  (State <-> ir-ctl text)
# ---------------------------------------------------------------------------


def _byte_to_bits_lsb(b: int) -> List[int]:
    return [(b >> i) & 1 for i in range(8)]


def _frame_to_mode2(frame: Sequence[int]) -> List[str]:
    """Encode one frame as mode2 lines (start mark + data bits)."""
    lines = ["pulse %d" % START_PULSE_US, "space %d" % START_SPACE_US]
    for b in frame:
        for bit in _byte_to_bits_lsb(b):
            lines.append("pulse %d" % PULSE_US)
            lines.append("space %d" % (SPACE_ONE_US if bit else SPACE_ZERO_US))
    lines.append("pulse %d" % PULSE_US)
    return lines


def dumps(state: State) -> str:
    """Encode State into ir-ctl mode2 text suitable for ``ir-ctl --send``."""
    f1, f3 = dump(state)
    lines = _frame_to_mode2(f1)
    lines.append("space %d" % GAP_US)
    lines.extend(_frame_to_mode2(f3))
    lines.append("space %d" % GAP_US)
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# IR text parsing  (ir-ctl output -> State)
# ---------------------------------------------------------------------------


def _token_number(t: str) -> Optional[int]:
    if t.isdigit():
        return int(t)
    m = re.search(r"\d+", t)
    return int(m.group(0)) if m else None


def _iter_events(line: str) -> Iterator[Tuple[str, int]]:
    """Yield ('pulse'|'space', µs) from one line of ir-ctl output."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return
    tokens = stripped.split()
    first = tokens[0].lower()
    if first == "timeout" and len(tokens) > 1:
        n = _token_number(tokens[1])
        if n is not None:
            yield "space", n
        return
    if first in ("carrier", "scancode"):
        return
    i = 0
    next_kind = "pulse"
    while i < len(tokens):
        t = tokens[i]
        if t.lower() in ("pulse", "space") and i + 1 < len(tokens):
            n = _token_number(tokens[i + 1])
            if n is not None:
                yield t.lower(), n
                i += 2
                continue
        n = _token_number(t)
        if n is not None:
            yield next_kind, n
            next_kind = "space" if next_kind == "pulse" else "pulse"
            i += 1
            continue
        i += 1


def _text_to_pairs(text: str) -> List[Tuple[int, int]]:
    """Convert ir-ctl text (any format) to (pulse_µs, space_µs) pairs."""
    pairs: List[Tuple[int, int]] = []
    last_pulse: Optional[int] = None
    for line in text.splitlines():
        for kind, us in _iter_events(line):
            if kind == "pulse":
                last_pulse = us
            elif kind == "space" and last_pulse is not None:
                pairs.append((last_pulse, us))
                last_pulse = None
    return pairs


def _split_at_gaps(pairs: List[Tuple[int, int]]) -> List[List[Tuple[int, int]]]:
    sub: List[List[Tuple[int, int]]] = []
    cur: List[Tuple[int, int]] = []
    for p, s in pairs:
        cur.append((p, s))
        if s >= GAP_MIN:
            sub.append(cur)
            cur = []
    if cur:
        sub.append(cur)
    return sub


def _decode_bits(pairs: List[Tuple[int, int]]) -> List[int]:
    bits: List[int] = []
    for pulse_us, space_us in pairs:
        if not (PULSE_MIN <= pulse_us <= PULSE_MAX):
            continue
        if SPACE_ZERO_MIN <= space_us <= SPACE_ZERO_MAX:
            bits.append(0)
        elif SPACE_ONE_MIN <= space_us <= SPACE_ONE_MAX:
            bits.append(1)
    out: List[int] = []
    for i in range(0, len(bits), 8):
        chunk = bits[i : i + 8]
        if len(chunk) < 8:
            break
        out.append(sum(b << j for j, b in enumerate(chunk)) & 0xFF)
    return out


def _classify(raw: List[int]) -> Optional[str]:
    """Return 'f1', 'f2', 'f3', or 'f3~' (truncated F3), else None.

    Recognises F2 (0x42) for ARC470A1 compatibility even though ARC452A9
    does not emit it.
    """
    has_header = len(raw) >= 5 and raw[:3] == HEADER
    if not has_header:
        return None
    chk = _checksum_ok(raw)
    if len(raw) == 8 and chk:
        if raw[4] == 0x42:
            return "f2"
        return "f1"
    if len(raw) == 19:
        return "f3" if chk else "f3~"
    if 9 <= len(raw) <= 18:
        return "f3~"
    return None


def _try_split_combined(raw: List[int]) -> Optional[List[Tuple[str, List[int]]]]:
    positions = [i for i in range(len(raw)) if raw[i : i + 3] == HEADER]
    if len(positions) < 2:
        return None
    result: List[Tuple[str, List[int]]] = []
    for idx, pos in enumerate(positions):
        end = positions[idx + 1] if idx + 1 < len(positions) else len(raw)
        frame = raw[pos:end]
        kind = _classify(frame)
        if kind:
            result.append((kind, frame))
    return result if result else None


def loads(ir_text: str) -> State:
    """Parse ir-ctl output (mode2 or +N-N compact) into State.

    Stores the original text in ``state.raw_ir``.
    """
    pairs = _text_to_pairs(ir_text)
    if not pairs:
        s = State()
        s.raw_ir = ir_text
        return s

    sub_frame_pairs = _split_at_gaps(pairs)
    f1_raw: Optional[List[int]] = None
    f3_raw: Optional[List[int]] = None

    for sf in sub_frame_pairs:
        raw = _decode_bits(sf)
        if not raw:
            continue
        kind = _classify(raw)
        if not kind:
            combined = _try_split_combined(raw)
            if combined:
                for ck, cr in combined:
                    if ck == "f1" and f1_raw is None:
                        f1_raw = cr
                    elif ck in ("f3", "f3~") and f3_raw is None:
                        f3_raw = cr
            continue
        if kind == "f1" and f1_raw is None:
            f1_raw = raw
        elif kind in ("f3", "f3~") and f3_raw is None:
            f3_raw = raw

    if f3_raw is not None:
        s = load(f3_raw, f1_raw)
    elif f1_raw is not None:
        s = State()
        s.raw_f1 = f1_raw
        if len(f1_raw) > 6:
            s.comfort = bool(f1_raw[6] & 0x10)
        s.truncated = True
    else:
        s = State()
        s.truncated = True

    s.raw_ir = ir_text
    return s


def iter_frames(ir_text: str) -> Iterator[Tuple[str, List[int]]]:
    """Yield (kind, raw_bytes) for every frame in ir_text. kind is 'f1', 'f2', 'f3', or 'f3~'."""
    pairs = _text_to_pairs(ir_text)
    if not pairs:
        return
    for segment in _split_at_gaps(pairs):
        for kind, raw in decode_segment(segment):
            yield kind, raw


def decode_segment(
    pairs: List[Tuple[int, int]],
) -> List[Tuple[str, List[int]]]:
    """Decode one gap-bounded segment into a list of (kind, raw_bytes)."""
    raw = _decode_bits(pairs)
    if not raw:
        return []
    combined = _try_split_combined(raw)
    if combined:
        return combined
    kind = _classify(raw)
    return [(kind, raw)] if kind else []


def iter_events(line: str) -> Iterator[Tuple[str, int]]:
    """Yield ('pulse'|'space', µs) from one line of ir-ctl mode2 output."""
    return _iter_events(line)


# ---------------------------------------------------------------------------
# Round-trip sanity
# ---------------------------------------------------------------------------


def round_trip_ok(state: State) -> bool:
    """True if dump(state) -> load() reproduces the same logical fields."""
    f1, f3 = dump(state)
    s2 = load(f3, f1)
    return (
        s2.power == state.power
        and s2.mode == state.mode
        and s2.half_c == state.half_c
        and s2.fan == state.fan
        and s2.swing == state.swing
        and s2.powerful == state.powerful
        and s2.econo == state.econo
        and s2.comfort == state.comfort
        and s2.timer_on_minutes == state.timer_on_minutes
        and s2.timer_off_minutes == state.timer_off_minutes
    )
