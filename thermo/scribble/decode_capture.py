#!/usr/bin/env python3
"""Decode all records in a daikin_recv capture pkl and print hex + checksums."""
import os
import pickle
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import importlib.util

spec = importlib.util.spec_from_file_location(
    "daikin_recv", os.path.join(os.path.dirname(os.path.abspath(__file__)), "daikin-recv.py")
)
dr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dr)

path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "captures", "daikin_recv_2026-02-24.pkl"
)
with open(path, "rb") as f:
    session = pickle.load(f)

print("Records:", len(session))
for i, r in enumerate(session):
    lines = r.get("raw_lines", [])
    total_chars = sum(len(l) for l in lines)
    desc = r.get("description", "?")
    label = r.get("label", "?")
    ts = r.get("timestamp", "?")

    pairs = dr.lines_to_pairs(lines)
    raw = dr.decode_bits(pairs) if pairs else []

    print(f"\n=== Record {i}: {label} desc={desc!r} ts={ts} ===")
    print(f"  lines={len(lines)} total_chars={total_chars} pairs={len(pairs)} raw_bytes={len(raw)}")
    if raw:
        print(f"  hex: {' '.join(f'{b:02x}' for b in raw)}")
        if len(raw) >= 8:
            print(f"  [:8]  chk: sum={sum(raw[:7])&0xff:02x} last={raw[7]:02x} ok={dr.checksum_ok(raw[:8])}")
        if len(raw) >= 16:
            print(f"  [8:16] chk: sum={sum(raw[8:15])&0xff:02x} last={raw[15]:02x} ok={dr.checksum_ok(raw[8:16])}")
        if len(raw) >= 27:
            print(f"  [16:27] chk: sum={sum(raw[16:26])&0xff:02x} last={raw[26]:02x} ok={dr.checksum_ok(raw[16:27])}")
    else:
        for j, l in enumerate(lines):
            print(f"  raw_line[{j}]: {l.rstrip()!r}")
