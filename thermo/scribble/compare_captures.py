#!/usr/bin/env python3
"""Compare decoded frames from two captures using blafois structure."""
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util

spec = importlib.util.spec_from_file_location(
    "daikin_recv",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "daikin-recv.py"),
)
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)

captures_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "captures")
pkls = sorted(
    f
    for f in os.listdir(captures_dir)
    if f.startswith("daikin_recv_") and f.endswith(".pkl")
)

frames = []
for pkl_name in pkls:
    path = os.path.join(captures_dir, pkl_name)
    with open(path, "rb") as f:
        session = pickle.load(f)
    for i, r in enumerate(session):
        lines = r.get("raw_lines", [])
        pairs = dr.lines_to_pairs(lines)
        raw = dr.decode_bits(pairs) if pairs else []
        if len(raw) >= 27:
            frames.append(
                {
                    "file": pkl_name,
                    "record": i,
                    "desc": r.get("description", "?"),
                    "label": r.get("label", "?"),
                    "ts": r.get("timestamp", "?"),
                    "raw": raw,
                }
            )

print(f"Found {len(frames)} decoded frame(s) across {len(pkls)} capture file(s).\n")

for fi, fr in enumerate(frames):
    raw = fr["raw"]
    print(f"--- Frame {fi}: {fr['file']} rec={fr['record']} {fr['label']} desc={fr['desc']!r} ts={fr['ts']} ---")
    print(f"  hex ({len(raw)} bytes): {' '.join(f'{b:02x}' for b in raw)}")
    # Blafois structure (treating as single 27-byte stream, i.e. F1[0:8] + F2[8:16] + F3[16:27])
    # F1 bytes 0-7
    print(f"  F1 [0:8]:  {' '.join(f'{b:02x}' for b in raw[0:8])}")
    print(f"    header: {' '.join(f'{b:02x}' for b in raw[0:4])}")
    print(f"    byte3={raw[3]:02x} byte4={raw[4]:02x} (expect 00 c5)")
    print(f"    byte6={raw[6]:02x} (comfort: {raw[6] & 0x10 != 0})")
    print(f"    byte7={raw[7]:02x} chk={sum(raw[:7])&0xff:02x} ok={dr.checksum_ok(raw[:8])}")
    # F2 bytes 8-15
    print(f"  F2 [8:16]: {' '.join(f'{b:02x}' for b in raw[8:16])}")
    print(f"    byte12={raw[12]:02x} (expect 42)")
    print(f"    byte15={raw[15]:02x} chk={sum(raw[8:15])&0xff:02x} ok={dr.checksum_ok(raw[8:16])}")
    # F3 bytes 16-26
    f3 = raw[16:27]
    print(f"  F3 [16:27]: {' '.join(f'{b:02x}' for b in f3)}")
    if len(f3) >= 11:
        b5 = f3[5]
        mode_nib = (b5 >> 4) & 0x0F
        power_bit = b5 & 0x01
        timer_off = (b5 >> 1) & 1
        timer_on = (b5 >> 2) & 1
        always1 = (b5 >> 3) & 1
        mode_map = {0: "AUTO", 2: "DRY", 3: "COOL", 4: "HEAT", 6: "FAN"}
        mode_s = mode_map.get(mode_nib, f"0x{mode_nib:x}")
        temp_raw = f3[6]
        temp_c = temp_raw / 2
        fan_byte = f3[8] if len(f3) > 8 else 0
        fan_nib = (fan_byte >> 4) & 0xF
        swing_nib = fan_byte & 0xF
        print(f"    byte5={b5:02x} -> mode={mode_s} power={'ON' if power_bit else 'OFF'} timer_on={timer_on} timer_off={timer_off} always1={always1}")
        print(f"    byte6={temp_raw:02x} -> temp={temp_c}C")
        print(f"    byte8={fan_byte:02x} -> fan=0x{fan_nib:x} swing={'on' if swing_nib==0xF else 'off'}")
        if len(f3) > 0xA - 16 + 16:
            # timer bytes relative to F3: offsets 0xa, 0xb, 0xc within F3 = indices 10, 11, 12 but F3 is only 11 bytes...
            pass
    print(f"    byte10={f3[10]:02x} chk={sum(f3[:10])&0xff:02x} ok={dr.checksum_ok(f3)}")
    print()

# Analyze pair distribution for each frame
for fi, fr in enumerate(frames):
    lines = None
    path = os.path.join(captures_dir, fr["file"])
    with open(path, "rb") as f:
        sess = pickle.load(f)
    rec = sess[fr["record"]]
    lines = rec.get("raw_lines", [])
    pairs = dr.lines_to_pairs(lines)
    print(f"--- Frame {fi}: pair analysis ---")
    print(f"  total pairs: {len(pairs)}")
    gaps = []
    data_bits = 0
    skipped_pulse = 0
    skipped_space = 0
    for pulse_us, space_us in pairs:
        if space_us > 10000:
            gaps.append((pulse_us, space_us))
        elif not (dr.PULSE_MIN <= pulse_us <= dr.PULSE_MAX):
            skipped_pulse += 1
        elif dr.SPACE_ZERO_MIN <= space_us <= dr.SPACE_ZERO_MAX:
            data_bits += 1
        elif dr.SPACE_ONE_MIN <= space_us <= dr.SPACE_ONE_MAX:
            data_bits += 1
        else:
            skipped_space += 1
    print(f"  data_bits={data_bits} ({data_bits // 8} bytes + {data_bits % 8} bits)")
    print(f"  skipped (bad pulse): {skipped_pulse}")
    print(f"  skipped (ambiguous space): {skipped_space}")
    print(f"  gaps (space>10ms): {len(gaps)}")
    for gi, (p, s) in enumerate(gaps):
        print(f"    gap[{gi}]: pulse={p} space={s}")
    # Show where gaps fall in the pair index
    for pi, (pulse_us, space_us) in enumerate(pairs):
        if space_us > 10000:
            print(f"    gap at pair index {pi}")
    print()

# Split at gaps and decode each sub-frame
for fi, fr in enumerate(frames):
    path = os.path.join(captures_dir, fr["file"])
    with open(path, "rb") as f:
        sess = pickle.load(f)
    rec = sess[fr["record"]]
    lines = rec.get("raw_lines", [])
    pairs = dr.lines_to_pairs(lines)
    # Split pairs at gaps (space > 10000us)
    sub_frames_pairs = []
    current = []
    for pulse_us, space_us in pairs:
        current.append((pulse_us, space_us))
        if space_us > 10000:
            sub_frames_pairs.append(current)
            current = []
    if current:
        sub_frames_pairs.append(current)
    print(f"--- Frame {fi}: split into {len(sub_frames_pairs)} sub-frame(s) at gaps ---")
    for si, sf_pairs in enumerate(sub_frames_pairs):
        raw_sf = dr.decode_bits(sf_pairs)
        print(f"  sub-frame {si}: {len(sf_pairs)} pairs -> {len(raw_sf)} bytes")
        if raw_sf:
            print(f"    hex: {' '.join(f'{b:02x}' for b in raw_sf)}")
            print(f"    chk: sum={sum(raw_sf[:-1])&0xff:02x} last={raw_sf[-1]:02x} ok={dr.checksum_ok(raw_sf)}")
            if len(raw_sf) >= 5:
                print(f"    header: {' '.join(f'{b:02x}' for b in raw_sf[:4])}  id_byte={raw_sf[4]:02x}")
    print()

# Compare if 2+ frames
if len(frames) >= 2:
    print("=== Byte-by-byte comparison ===")
    for pos in range(min(len(f["raw"]) for f in frames)):
        vals = [f["raw"][pos] for f in frames]
        same = all(v == vals[0] for v in vals)
        marker = " " if same else " <-- DIFFERS"
        vstr = " | ".join(f"{v:02x}" for v in vals)
        print(f"  byte[{pos:2d}]: {vstr}{marker}")
