#!/usr/bin/env python3
"""Propose cross-provider synonym map updates from album co-occurrence.

Does **not** rewrite ``synonyms/*.json`` by default. Emits a reviewable report
(and optional map-patch proposals for keys absent from the current maps).

## I/O contract

**Inputs**
- ``root``: FLAC files tree (``/mnt/sdb2/music/flac/files``). Scans album dirs
  for ``.meta.<provider>.json``; skips ``_tags/``, skips ``combined`` / ``johan``.
- Per album, bag = ``metadata.genres`` ∪ ``metadata.tags`` (strings) per provider.
- Optional ``--synonyms-dir``: existing maps as priors (already-mapped keys are
  not proposed for overwrite unless ``--force-mapped``).

**Positive synonym evidence** (``candidates``)
- Cross-provider pairs with **equal slugs** after ``tag_classify.slug``,
  same axis, support ≥ ``--min-support`` (e.g. ``Country Rock`` ↔ ``country rock``).

**Related-but-not-synonym** (``related``)
- Same-axis pairs with high PMI/Jaccard but **different** slugs (e.g.
  ``Downtempo`` ↔ ``chillout``). Review-only; never clustered into map patches.

**Axis / non-synonym evidence** (``non_synonyms``)
- ``tag_classify.year_value`` / ``artist_canonical`` assign an axis
  (``year`` / ``artist`` / ``genre``). Different axes → never synonym.
- Same axis ``year`` or ``artist`` with different canonical values → never
  synonym (``80s`` ↛ ``90s``; ``leonardcohen`` ↛ ``tomwaits``).

**Outputs** (``--out`` directory)
- ``report.json``: candidates, related, non_synonyms, clusters, stats.
- ``report.tsv``: flat synonym-candidate rows for review.
- ``map_patch.json`` (if ``--write-patch``): per-provider ``{raw: type;value}``
  from synonym clusters only (no overwrite unless ``--force-mapped``).

Runtime postingest stays map + heuristic; this tool is offline groom only.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator, Optional

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SYNONYMS = ROOT / "synonyms"
SHADUP = ROOT.parents[1] / "shadup"
if str(SHADUP) not in sys.path:
    sys.path.insert(0, str(SHADUP))

import tag_classify as tc  # noqa: E402

PROVIDERS = ("discogs", "lastfm", "musicbrainz")
Axis = str  # year | artist | genre


@dataclass(frozen=True)
class Label:
    provider: str
    raw: str

    @property
    def key(self) -> str:
        return f"{self.provider}:{self.raw}"


@dataclass
class LabelStats:
    axis: Axis
    canon: str  # type;value proposal from heuristics
    slug: str
    albums: set[str] = field(default_factory=set)


def iter_album_dirs(root: Path) -> Iterator[Path]:
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name.startswith(".") or p.name == "_tags":
            continue
        yield p


def load_album_bags(
    album: Path, providers: Iterable[str] = PROVIDERS
) -> dict[str, set[str]]:
    bags: dict[str, set[str]] = {}
    for prov in providers:
        path = album / f".meta.{prov}.json"
        if not path.is_file():
            continue
        try:
            md = json.loads(path.read_text(encoding="utf-8")).get("metadata") or {}
        except (OSError, json.JSONDecodeError):
            continue
        raws: set[str] = set()
        for field_name in ("genres", "tags"):
            for item in md.get(field_name) or []:
                if isinstance(item, str) and item.strip():
                    raws.add(item.strip())
        if raws:
            bags[prov] = raws
    return bags


def axis_and_canon(raw: str) -> tuple[Axis, str]:
    """Return (axis, proposed type;value) using tag_classify priors."""
    yv = tc.year_value(raw)
    if yv:
        return "year", f"year;{yv}"
    alias = tc.artist_canonical(raw)
    if alias:
        return "artist", f"artist;{alias}"
    mapped = tc.classify_raw(raw)
    if mapped is None:
        return "genre", f"genre;{tc.slug(raw)}"
    typ, _, val = mapped.partition(";")
    if typ == "year":
        return "year", mapped
    if typ == "artist":
        return "artist", mapped
    if typ == "collection":
        return "genre", mapped  # treat as genre-axis for synonymy
    return "genre", mapped if mapped else f"genre;{tc.slug(raw)}"


def is_non_synonym(a: LabelStats, b: LabelStats) -> Optional[str]:
    """Return reason string if *a* and *b* must not merge; else None."""
    if a.axis != b.axis:
        return f"axis_mismatch:{a.axis}!={b.axis}"
    if a.axis in {"year", "artist"} and a.canon != b.canon:
        return f"same_axis_different_value:{a.canon}!={b.canon}"
    return None


def pmi(co: int, na: int, nb: int, n_albums: int) -> float:
    if co <= 0 or na <= 0 or nb <= 0 or n_albums <= 0:
        return float("-inf")
    # Pointwise PMI with album as unit
    return math.log2((co * n_albums) / (na * nb))


def jaccard(a: set[str], b: set[str]) -> float:
    if not a and not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


class UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, x: str) -> str:
        if x not in self.parent:
            self.parent[x] = x
            return x
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def load_existing_maps(synonyms_dir: Path) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for prov in PROVIDERS:
        path = synonyms_dir / f"{prov}.json"
        if not path.is_file():
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        out[prov] = dict(doc.get("map") or {})
    return out


def propose(
    root: Path,
    *,
    min_support: int = 2,
    min_pmi: float = 1.0,
    min_jaccard: float = 0.15,
    synonyms_dir: Optional[Path] = None,
    force_mapped: bool = False,
) -> dict:
    label_stats: dict[str, LabelStats] = {}
    album_labels: list[tuple[str, dict[str, set[str]]]] = []

    for album in iter_album_dirs(root):
        bags = load_album_bags(album)
        if len(bags) < 2:
            continue
        album_id = album.name
        album_labels.append((album_id, bags))
        for prov, raws in bags.items():
            for raw in raws:
                key = f"{prov}:{raw}"
                if key not in label_stats:
                    axis, canon = axis_and_canon(raw)
                    label_stats[key] = LabelStats(
                        axis=axis, canon=canon, slug=tc.slug(raw)
                    )
                label_stats[key].albums.add(album_id)

    n_albums = len(album_labels)
    pair_co: Counter[tuple[str, str]] = Counter()

    for _album_id, bags in album_labels:
        # Cross-provider pairs only (ordered by provider name for stability)
        provs = sorted(bags)
        for i, pa in enumerate(provs):
            for pb in provs[i + 1 :]:
                for ra in bags[pa]:
                    for rb in bags[pb]:
                        ka, kb = f"{pa}:{ra}", f"{pb}:{rb}"
                        if ka > kb:
                            ka, kb = kb, ka
                        pair_co[(ka, kb)] += 1

    candidates: list[dict] = []
    related: list[dict] = []
    non_synonyms: list[dict] = []
    uf = UnionFind()

    for (ka, kb), co in pair_co.items():
        if co < min_support:
            continue
        sa, sb = label_stats[ka], label_stats[kb]
        reason = is_non_synonym(sa, sb)
        na, nb = len(sa.albums), len(sb.albums)
        score_pmi = pmi(co, na, nb, n_albums)
        score_jac = jaccard(sa.albums, sb.albums)
        slug_eq = sa.slug == sb.slug and sa.slug != "empty"
        row = {
            "a": ka,
            "b": kb,
            "support": co,
            "pmi": None if score_pmi == float("-inf") else round(score_pmi, 4),
            "jaccard": round(score_jac, 4),
            "slug_equal": slug_eq,
            "canon_a": sa.canon,
            "canon_b": sb.canon,
            "axis_a": sa.axis,
            "axis_b": sb.axis,
        }
        if reason:
            row["reason"] = reason
            non_synonyms.append(row)
            continue
        if slug_eq:
            proposed = f"{sa.axis};{sa.slug}" if sa.axis != "genre" else f"genre;{sa.slug}"
            row["proposed"] = proposed
            candidates.append(row)
            uf.union(ka, kb)
        elif score_pmi >= min_pmi and score_jac >= min_jaccard:
            row["note"] = "cooccur_not_slug"
            related.append(row)

    # Clusters from synonym edges
    clusters_map: dict[str, list[str]] = defaultdict(list)
    for key in label_stats:
        if key in uf.parent or any(
            key in (c["a"], c["b"]) for c in candidates
        ):
            clusters_map[uf.find(key)].append(key)
    # Only clusters touched by at least one candidate edge
    touched = {uf.find(c["a"]) for c in candidates} | {
        uf.find(c["b"]) for c in candidates
    }
    clusters: list[dict] = []
    for root_key in sorted(touched):
        members = sorted(set(clusters_map[root_key]))
        if len(members) < 2:
            continue
        canons = [label_stats[m].canon for m in members]
        # Majority / shortest slug genre
        proposed = Counter(canons).most_common(1)[0][0]
        slugs = {label_stats[m].slug for m in members}
        if len(slugs) == 1:
            axis = label_stats[members[0]].axis
            s = next(iter(slugs))
            proposed = f"{axis};{s}" if axis != "genre" else f"genre;{s}"
        clusters.append(
            {
                "members": members,
                "proposed": proposed,
                "size": len(members),
            }
        )

    existing = load_existing_maps(synonyms_dir or DEFAULT_SYNONYMS)
    map_patch: dict[str, dict[str, str]] = {p: {} for p in PROVIDERS}
    for cluster in clusters:
        proposed = cluster["proposed"]
        for member in cluster["members"]:
            prov, _, raw = member.partition(":")
            cur = existing.get(prov, {}).get(raw)
            if cur is None or force_mapped:
                if cur is None or cur != proposed:
                    map_patch[prov][raw] = proposed
            elif cur != proposed:
                # conflict noted on cluster
                cluster.setdefault("conflicts", []).append(
                    {"provider": prov, "raw": raw, "mapped": cur, "proposed": proposed}
                )

    # Drop empty provider patches
    map_patch = {p: m for p, m in map_patch.items() if m}

    candidates.sort(key=lambda r: (-r["support"], -(r["pmi"] or -99), r["a"], r["b"]))
    related.sort(key=lambda r: (-r["support"], -(r["pmi"] or -99), r["a"], r["b"]))
    non_synonyms.sort(key=lambda r: (-r["support"], r["a"], r["b"]))
    clusters.sort(key=lambda c: (-c["size"], c["proposed"]))

    return {
        "stats": {
            "multi_provider_albums": n_albums,
            "labels": len(label_stats),
            "pair_edges_ge_min_support": sum(
                1 for _k, c in pair_co.items() if c >= min_support
            ),
            "candidates": len(candidates),
            "related": len(related),
            "non_synonyms": len(non_synonyms),
            "clusters": len(clusters),
            "min_support": min_support,
            "min_pmi": min_pmi,
            "min_jaccard": min_jaccard,
        },
        "candidates": candidates,
        "related": related,
        "non_synonyms": non_synonyms,
        "clusters": clusters,
        "map_patch": map_patch,
    }


def write_report(doc: dict, out: Path, *, write_patch: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = [
        "support\tpmi\tjaccard\tslug_equal\tproposed\ta\tb\tcanon_a\tcanon_b"
    ]
    for r in doc["candidates"]:
        lines.append(
            "\t".join(
                [
                    str(r["support"]),
                    str(r["pmi"]),
                    str(r["jaccard"]),
                    str(r["slug_equal"]),
                    r.get("proposed", ""),
                    r["a"],
                    r["b"],
                    r["canon_a"],
                    r["canon_b"],
                ]
            )
        )
    (out / "report.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if write_patch:
        (out / "map_patch.json").write_text(
            json.dumps(doc["map_patch"], indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "root",
        type=Path,
        help="FLAC files root (album dirs with .meta.*.json)",
    )
    p.add_argument(
        "--out",
        type=Path,
        required=True,
        help="Directory for report.json / report.tsv / map_patch.json",
    )
    p.add_argument("--min-support", type=int, default=2)
    p.add_argument("--min-pmi", type=float, default=1.0)
    p.add_argument("--min-jaccard", type=float, default=0.15)
    p.add_argument(
        "--synonyms-dir",
        type=Path,
        default=DEFAULT_SYNONYMS,
        help="Existing synonym maps (default: skill synonyms/)",
    )
    p.add_argument(
        "--write-patch",
        action="store_true",
        help="Also write map_patch.json (additions only)",
    )
    p.add_argument(
        "--force-mapped",
        action="store_true",
        help="Allow patch entries that overwrite existing map keys",
    )
    args = p.parse_args(argv)

    doc = propose(
        args.root,
        min_support=args.min_support,
        min_pmi=args.min_pmi,
        min_jaccard=args.min_jaccard,
        synonyms_dir=args.synonyms_dir,
        force_mapped=args.force_mapped,
    )
    write_report(doc, args.out, write_patch=args.write_patch)
    s = doc["stats"]
    print(
        f"albums={s['multi_provider_albums']} labels={s['labels']} "
        f"candidates={s['candidates']} related={s['related']} "
        f"non_synonyms={s['non_synonyms']} clusters={s['clusters']} → {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
