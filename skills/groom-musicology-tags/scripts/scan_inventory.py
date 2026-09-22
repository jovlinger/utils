#!/usr/bin/env python3
"""Scan .meta.*.json under a FLAC files root; write per-provider tag/genre TSVs.

Output lines: ``<count>\\t<field>:<raw>`` sorted by count desc, then key.
"""

from __future__ import annotations

import argparse
import collections
import json
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path, help="e.g. /mnt/sdb2/music/flac/files")
    p.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Directory for <provider>.tsv files",
    )
    args = p.parse_args()
    root: Path = args.root
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    by: dict[str, collections.Counter[str]] = collections.defaultdict(
        collections.Counter
    )
    for meta in root.rglob(".meta.*.json"):
        if "_tags" in meta.parts:
            continue
        prov = meta.name[len(".meta.") : -len(".json")]
        try:
            md = json.loads(meta.read_text(encoding="utf-8")).get("metadata") or {}
        except (OSError, json.JSONDecodeError):
            continue
        for t in md.get("tags") or []:
            if isinstance(t, str) and t.strip():
                by[prov][f"tag:{t.strip()}"] += 1
        for g in md.get("genres") or []:
            if isinstance(g, str) and g.strip():
                by[prov][f"genre:{g.strip()}"] += 1

    for prov, ctr in sorted(by.items()):
        lines = [
            f"{c}\t{k}"
            for k, c in sorted(ctr.items(), key=lambda kv: (-kv[1], kv[0].lower()))
        ]
        (out / f"{prov}.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"{prov}: {len(lines)} rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
