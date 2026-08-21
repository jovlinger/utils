#!/usr/bin/env python3
"""Collect provider tags into a lightly normalized vocabulary set.

Minimal normalization (no aggressive stemming):
- strip surrounding whitespace
- casefold for the grouping key; retain the most frequent surface form
- unify ``-`` / ``_`` / whitespace runs to a single space in the key
- strip surrounding punctuation from the key
- optional trailing ``s`` peel only when both forms appear in the corpus
  (``albums``/``album``), never blind Porter stemming

Writes ``vocab.json`` consumed by ``agent_synonym_sets.py``.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable, Optional

PROVIDERS = ("discogs", "lastfm", "musicbrainz", "johan")

_SPACE = re.compile(r"[\s_\-]+")
_EDGE_PUNCT = re.compile(r"^[\W_]+|[\W_]+$", re.UNICODE)


def surface_key(raw: str) -> str:
    """Casefold + light punct/space unify. Not a stemmer."""
    s = raw.strip().casefold()
    s = _SPACE.sub(" ", s)
    s = _EDGE_PUNCT.sub("", s)
    s = _SPACE.sub(" ", s).strip()
    return s or raw.strip().casefold() or "empty"


def prefer_surface(counter: Counter[str]) -> str:
    """Most frequent raw; ties → shortest then lexicographic."""
    return sorted(counter.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0].lower()))[
        0
    ][0]


def load_inventory_raws(inventory_dir: Path) -> dict[str, Counter[str]]:
    """provider -> Counter[raw]."""
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for tsv in sorted(inventory_dir.glob("*.tsv")):
        prov = tsv.stem
        for line in tsv.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            count_s, key = line.split("\t", 1)
            _field, _, raw = key.partition(":")
            raw = raw.strip()
            if raw:
                out[prov][raw] += int(count_s)
    return out


def load_sidecar_raws(files_root: Path) -> dict[str, Counter[str]]:
    out: dict[str, Counter[str]] = defaultdict(Counter)
    for meta in files_root.rglob(".meta.*.json"):
        if "_tags" in meta.parts:
            continue
        prov = meta.name[len(".meta.") : -len(".json")]
        if prov in {"combined"}:
            continue
        try:
            md = json.loads(meta.read_text(encoding="utf-8")).get("metadata") or {}
        except (OSError, json.JSONDecodeError):
            continue
        for field_name in ("genres", "tags"):
            for item in md.get(field_name) or []:
                if isinstance(item, str) and item.strip():
                    out[prov][item.strip()] += 1
    return out


def merge_provider_counts(
    *sources: dict[str, Counter[str]],
) -> dict[str, Counter[str]]:
    merged: dict[str, Counter[str]] = defaultdict(Counter)
    for src in sources:
        for prov, ctr in src.items():
            merged[prov].update(ctr)
    return merged


def build_vocab(
    by_provider: dict[str, Counter[str]],
    *,
    include_providers: Optional[Iterable[str]] = None,
) -> dict:
    allow = set(include_providers) if include_providers else None
    # key -> Counter[raw], and key -> Counter[provider]
    key_raws: dict[str, Counter[str]] = defaultdict(Counter)
    key_provs: dict[str, Counter[str]] = defaultdict(Counter)
    key_total: Counter[str] = Counter()

    for prov, ctr in by_provider.items():
        if allow is not None and prov not in allow:
            continue
        for raw, n in ctr.items():
            k = surface_key(raw)
            key_raws[k][raw] += n
            key_provs[k][prov] += n
            key_total[k] += n

    # Optional plural peel: only if both key and key without trailing s exist
    plural_merge: dict[str, str] = {}
    for k in list(key_total):
        if len(k) > 4 and k.endswith("s") and not k.endswith("ss"):
            base = k[:-1]
            if base in key_total:
                plural_merge[k] = base

    if plural_merge:
        for child, parent in plural_merge.items():
            key_raws[parent].update(key_raws.pop(child))
            key_provs[parent].update(key_provs.pop(child))
            key_total[parent] += key_total.pop(child)

    entries = []
    for k, total in sorted(key_total.items(), key=lambda kv: (-kv[1], kv[0])):
        entries.append(
            {
                "key": k,
                "surface": prefer_surface(key_raws[k]),
                "count": total,
                "variants": [
                    {"raw": raw, "count": n}
                    for raw, n in sorted(
                        key_raws[k].items(), key=lambda kv: (-kv[1], kv[0].lower())
                    )
                ],
                "providers": dict(sorted(key_provs[k].items())),
            }
        )

    return {
        "normalization": {
            "casefold": True,
            "hyphen_underscore_to_space": True,
            "edge_punct_strip": True,
            "plural_peel": "only_when_both_forms_present",
            "porter_stem": False,
        },
        "size": len(entries),
        "entries": entries,
    }


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--inventory",
        type=Path,
        help="inventory/ dir of provider TSVs (preferred, fast)",
    )
    p.add_argument(
        "--files-root",
        type=Path,
        help="Optional live FLAC files root to scan sidecars",
    )
    p.add_argument(
        "--out",
        type=Path,
        required=True,
        help="vocab.json path",
    )
    p.add_argument(
        "--providers",
        default="discogs,lastfm,musicbrainz",
        help="Comma list (default skips johan). Use ALL for every provider.",
    )
    args = p.parse_args(argv)
    if not args.inventory and not args.files_root:
        p.error("need --inventory and/or --files-root")

    sources: list[dict[str, Counter[str]]] = []
    if args.inventory:
        sources.append(load_inventory_raws(args.inventory))
    if args.files_root:
        sources.append(load_sidecar_raws(args.files_root))
    merged = merge_provider_counts(*sources)

    if args.providers.strip().upper() == "ALL":
        allow = None
    else:
        allow = [x.strip() for x in args.providers.split(",") if x.strip()]

    doc = build_vocab(merged, include_providers=allow)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"vocab size={doc['size']} → {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
