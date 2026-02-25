#!/usr/bin/env python3
"""Print every F1/F2/F3 frame (hex) from an ir_capture log. Thin wrapper around heatpumpirctl."""
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "onboard"))
from heatpumpirctl import ARC452A9 as proto


def main() -> None:
    path = sys.argv[1] if len(sys.argv) > 1 else None
    if not path or not os.path.isfile(path):
        sys.stderr.write("Usage: %s <ir_capture.log>\n" % sys.argv[0])
        sys.exit(1)
    with open(path) as f:
        data_lines: list[str] = []
        desc = ""
        for line in f:
            if line.startswith("#"):
                if data_lines:
                    _dump_frames("".join(data_lines), desc)
                    data_lines = []
                m = re.search(r"description=(.+?)(?:\s{2,}|$)", line)
                desc = m.group(1).strip() if m else ""
            elif line.strip():
                data_lines.append(line)
        if data_lines:
            _dump_frames("".join(data_lines), desc)


def _dump_frames(ir_text: str, desc: str) -> None:
    print("# description=%s" % desc)
    for kind, raw in proto.iter_frames(ir_text):
        print("%s %s" % (kind, " ".join("%02x" % b for b in raw)))
    print()


if __name__ == "__main__":
    main()
