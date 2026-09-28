#!/usr/bin/env python3
"""Propose cross-provider synonym map updates from album co-occurrence.

Does **not** rewrite ``synonyms/*.json`` by default. Emits a reviewable report
(and optional map-patch proposals for keys absent from the current maps).

## Statistical signals (validated on the FLAC corpus)

On the same album:

- **Cross-provider** co-occurrence of two labels (provider A has *x*, provider B
  has *y*) is a signal **for synonymy** — especially when ``slug(x) == slug(y)``
  (246/299 multi-provider albums share at least one identical slug). Different
  slugs are weaker: many cross edges are still facet mixes (Discogs genre ×
  Last.fm decade), so we require a high ``cross / (cross+within)`` fraction and
  minimum cross support.
- **Within-provider** co-occurrence (both labels in one provider's bag) is a
  signal for **orthogonality** — a provider rarely emits redundant synonyms on
  one album; those pairs are facets (``90s``+``alternative``, ``chillout``+
  ``femalevocalists``). Within-heavy pairs are emitted as ``non_synonyms``.

Axes such as year vs genre are **not** hard-coded; they are expected to arise
as within-heavy (orthogonal) structure. ``tag_classify`` is only used to
propose a ``type;value`` string for accepted synonym clusters.

## Outputs (``--out``)

- ``report.json``: candidates, non_synonyms, clusters, stats
- ``report.tsv``: synonym-candidate rows
- ``map_patch.json`` (``--write-patch``): additions only unless ``--force-mapped``
"""

from __future__ import annotations

import argparse
import json
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


@dataclass
class PairStats:
    cross: int = 0  # albums with labels from different providers
    within: int = 0  # albums with both labels in one provider bag
    cross_examples: list[dict] = field(default_factory=list)
    within_examples: list[dict] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.cross + self.within

    @property
    def cross_frac(self) -> Optional[float]:
        if self.total == 0:
            return None
        return self.cross / self.total


@dataclass
class SlugInfo:
    """Aggregate raw forms per provider for one slug."""

    albums: set[str] = field(default_factory=set)
    raws: dict[str, Counter] = field(
        default_factory=lambda: defaultdict(Counter)
    )  # provider -> Counter[raw]


def iter_album_dirs(root: Path) -> Iterator[Path]:
    for p in sorted(root.iterdir()):
        if not p.is_dir() or p.name.startswith(".") or p.name == "_tags":
            continue
        yield p


def load_album_provider_bags(
    album: Path, providers: Iterable[str] = PROVIDERS
) -> dict[str, dict[str, str]]:
    """Return provider -> {slug: one raw string}."""
    bags: dict[str, dict[str, str]] = {}
    for prov in providers:
        path = album / f".meta.{prov}.json"
        if not path.is_file():
            continue
        try:
            md = json.loads(path.read_text(encoding="utf-8")).get("metadata") or {}
        except (OSError, json.JSONDecodeError):
            continue
        slug_to_raw: dict[str, str] = {}
        for field_name in ("genres", "tags"):
            for item in md.get(field_name) or []:
                if isinstance(item, str) and item.strip():
                    raw = item.strip()
                    sl = tc.slug(raw)
                    slug_to_raw.setdefault(sl, raw)
        if slug_to_raw:
            bags[prov] = slug_to_raw
    return bags


def pair_key(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


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


def propose_canon_for_slug(slug: str, raw_samples: list[str]) -> str:
    """Map a slug cluster to type;value via tag_classify on a sample raw."""
    for raw in raw_samples:
        mapped = tc.classify_raw(raw)
        if mapped:
            return tc.canonicalize_tag(mapped) or mapped
    mapped = tc.classify_raw(slug)
    if mapped:
        return tc.canonicalize_tag(mapped) or mapped
    return f"genre;{slug}"


def near_slug(a: str, b: str) -> bool:
    """Weak string prior: containment or shared long prefix (not required)."""
    if a == b:
        return True
    if a in b or b in a:
        return True
    if len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4]:
        return True
    return False


def propose(
    root: Path,
    *,
    min_cross: int = 3,
    min_within: int = 3,
    synonym_cross_frac: float = 0.65,
    ortho_cross_frac: float = 0.35,
    synonyms_dir: Optional[Path] = None,
    force_mapped: bool = False,
) -> dict:
    """Score slug pairs from cross- vs within-provider album co-occurrence."""
    pairs: dict[tuple[str, str], PairStats] = defaultdict(PairStats)
    slug_info: dict[str, SlugInfo] = defaultdict(SlugInfo)
    multi_provider_albums = 0
    same_slug_agree_albums = 0

    for album in iter_album_dirs(root):
        bags = load_album_provider_bags(album)
        if not bags:
            continue
        album_id = album.name

        # slug inventory
        for prov, slug_raws in bags.items():
            for sl, raw in slug_raws.items():
                info = slug_info[sl]
                info.albums.add(album_id)
                info.raws[prov][raw] += 1

        # within-provider orthogonality evidence
        for prov, slug_raws in bags.items():
            slugs = sorted(slug_raws)
            for i, a in enumerate(slugs):
                for b in slugs[i + 1 :]:
                    key = pair_key(a, b)
                    st = pairs[key]
                    st.within += 1
                    if len(st.within_examples) < 3:
                        st.within_examples.append(
                            {
                                "album": album_id,
                                "provider": prov,
                                "raw_a": slug_raws[a],
                                "raw_b": slug_raws[b],
                            }
                        )

        if len(bags) < 2:
            continue
        multi_provider_albums += 1

        # same-slug agreement across providers
        inter: Optional[set[str]] = None
        for slug_raws in bags.values():
            s = set(slug_raws)
            inter = s if inter is None else inter & s
        if inter:
            same_slug_agree_albums += 1

        # cross-provider synonym evidence (album-unique unordered pairs)
        provs = sorted(bags)
        seen_cross: set[tuple[str, str]] = set()
        for i, pa in enumerate(provs):
            for pb in provs[i + 1 :]:
                for a, raw_a in bags[pa].items():
                    for b, raw_b in bags[pb].items():
                        if a == b:
                            continue  # identical slug — trivial synonym
                        key = pair_key(a, b)
                        if key in seen_cross:
                            continue
                        seen_cross.add(key)
                        st = pairs[key]
                        st.cross += 1
                        if len(st.cross_examples) < 3:
                            st.cross_examples.append(
                                {
                                    "album": album_id,
                                    "a": f"{pa}:{raw_a}",
                                    "b": f"{pb}:{raw_b}",
                                }
                            )
        for key in seen_cross:
            pass  # counted above once per key

    candidates: list[dict] = []
    non_synonyms: list[dict] = []
    uf = UnionFind()

    for (a, b), st in pairs.items():
        frac = st.cross_frac
        row = {
            "a": a,
            "b": b,
            "cross": st.cross,
            "within": st.within,
            "cross_frac": None if frac is None else round(frac, 4),
            "near_slug": near_slug(a, b),
            "cross_examples": st.cross_examples,
            "within_examples": st.within_examples,
        }

        # Orthogonal: within-heavy (provider listed both as distinct facets)
        if st.within >= min_within and (frac is None or frac <= ortho_cross_frac):
            row["reason"] = "within_provider_orthogonal"
            non_synonyms.append(row)
            continue

        # Synonym: cross-heavy. Different slugs need a near-slug string prior —
        # bare cross_frac is polluted by Discogs-genre × Last.fm-decade pairs.
        if (
            st.cross >= min_cross
            and frac is not None
            and frac >= synonym_cross_frac
            and near_slug(a, b)
        ):
            proposed_a = propose_canon_for_slug(
                a, [raw for ctr in slug_info[a].raws.values() for raw in ctr]
            )
            proposed_b = propose_canon_for_slug(
                b, [raw for ctr in slug_info[b].raws.values() for raw in ctr]
            )
            # containment → longer descriptive slug often wins (alternativerock)
            core = a if len(a) >= len(b) else b
            proposed = propose_canon_for_slug(
                core, [raw for ctr in slug_info[core].raws.values() for raw in ctr]
            )
            if proposed_a == proposed_b:
                proposed = proposed_a
            row["proposed"] = proposed
            candidates.append(row)
            uf.union(a, b)
            continue

        # Cross-heavy but not near-slug: likely facet mix across providers
        # (e.g. Electronic × 80s). Keep out of synonym clusters.
        if (
            st.cross >= min_cross
            and frac is not None
            and frac >= synonym_cross_frac
            and not near_slug(a, b)
        ):
            row["reason"] = "cross_heavy_not_near_slug"
            non_synonyms.append(row)
            continue

    # Clusters from synonym edges
    clusters_map: dict[str, list[str]] = defaultdict(list)
    for a, b in ((r["a"], r["b"]) for r in candidates):
        clusters_map[uf.find(a)].append(a)
        clusters_map[uf.find(b)].append(b)

    clusters: list[dict] = []
    for root_slug, members in clusters_map.items():
        members = sorted(set(members))
        if len(members) < 2:
            continue
        # pick canon from most album-frequent member
        members.sort(key=lambda s: (-len(slug_info[s].albums), s))
        head = members[0]
        raws = [raw for ctr in slug_info[head].raws.values() for raw in ctr]
        proposed = propose_canon_for_slug(head, raws)
        clusters.append({"members": members, "proposed": proposed, "size": len(members)})

    existing = load_existing_maps(synonyms_dir or DEFAULT_SYNONYMS)
    map_patch: dict[str, dict[str, str]] = {p: {} for p in PROVIDERS}
    for cluster in clusters:
        proposed = cluster["proposed"]
        for sl in cluster["members"]:
            info = slug_info[sl]
            for prov, ctr in info.raws.items():
                for raw, _n in ctr.items():
                    cur = existing.get(prov, {}).get(raw)
                    if cur is None or (force_mapped and cur != proposed):
                        if cur is None or cur != proposed:
                            map_patch[prov][raw] = proposed
                    elif cur != proposed:
                        cluster.setdefault("conflicts", []).append(
                            {
                                "provider": prov,
                                "raw": raw,
                                "mapped": cur,
                                "proposed": proposed,
                            }
                        )

    map_patch = {p: m for p, m in map_patch.items() if m}

    candidates.sort(
        key=lambda r: (-r["cross"], -(r["cross_frac"] or 0), r["a"], r["b"])
    )
    non_synonyms.sort(
        key=lambda r: (-r["within"], r["cross_frac"] or 0, r["a"], r["b"])
    )
    clusters.sort(key=lambda c: (-c["size"], c["proposed"]))

    # Same-slug trivial synonyms: every slug seen under ≥2 providers
    same_slug_multi: list[dict] = []
    for sl, info in slug_info.items():
        provs_present = [p for p in PROVIDERS if info.raws.get(p)]
        if len(provs_present) < 2:
            continue
        proposed = propose_canon_for_slug(
            sl, [raw for ctr in info.raws.values() for raw in ctr]
        )
        same_slug_multi.append(
            {
                "slug": sl,
                "providers": provs_present,
                "albums": len(info.albums),
                "proposed": proposed,
                "raws": {p: ctr.most_common(3) for p, ctr in info.raws.items()},
            }
        )
        # ensure map patch covers raw variants toward same canon
        for prov, ctr in info.raws.items():
            for raw, _n in ctr.items():
                cur = existing.get(prov, {}).get(raw)
                if cur is None or (force_mapped and cur != proposed):
                    if cur != proposed:
                        map_patch.setdefault(prov, {})[raw] = proposed

    same_slug_multi.sort(key=lambda r: -r["albums"])

    return {
        "stats": {
            "multi_provider_albums": multi_provider_albums,
            "same_slug_agree_albums": same_slug_agree_albums,
            "slugs": len(slug_info),
            "pairs_scored": len(pairs),
            "candidates": len(candidates),
            "non_synonyms": len(non_synonyms),
            "clusters": len(clusters),
            "same_slug_multi_provider": len(same_slug_multi),
            "min_cross": min_cross,
            "min_within": min_within,
            "synonym_cross_frac": synonym_cross_frac,
            "ortho_cross_frac": ortho_cross_frac,
        },
        "same_slug_multi_provider": same_slug_multi,
        "candidates": candidates,
        "non_synonyms": non_synonyms,
        "clusters": clusters,
        "map_patch": map_patch,
    }


def write_report(doc: dict, out: Path, *, write_patch: bool) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(
        json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    lines = ["cross\twithin\tcross_frac\tnear_slug\tproposed\ta\tb"]
    for r in doc["candidates"]:
        lines.append(
            "\t".join(
                [
                    str(r["cross"]),
                    str(r["within"]),
                    str(r["cross_frac"]),
                    str(r["near_slug"]),
                    r.get("proposed", ""),
                    r["a"],
                    r["b"],
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
    p.add_argument("root", type=Path, help="FLAC files root")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--min-cross", type=int, default=3)
    p.add_argument("--min-within", type=int, default=3)
    p.add_argument(
        "--synonym-cross-frac",
        type=float,
        default=0.65,
        help="Min cross/(cross+within) to call synonym",
    )
    p.add_argument(
        "--ortho-cross-frac",
        type=float,
        default=0.35,
        help="Max cross/(cross+within) to call within-orthogonal",
    )
    p.add_argument("--synonyms-dir", type=Path, default=DEFAULT_SYNONYMS)
    p.add_argument("--write-patch", action="store_true")
    p.add_argument("--force-mapped", action="store_true")
    args = p.parse_args(argv)

    doc = propose(
        args.root,
        min_cross=args.min_cross,
        min_within=args.min_within,
        synonym_cross_frac=args.synonym_cross_frac,
        ortho_cross_frac=args.ortho_cross_frac,
        synonyms_dir=args.synonyms_dir,
        force_mapped=args.force_mapped,
    )
    write_report(doc, args.out, write_patch=args.write_patch)
    s = doc["stats"]
    print(
        f"multi={s['multi_provider_albums']} same_slug_agree={s['same_slug_agree_albums']} "
        f"candidates={s['candidates']} non_synonyms={s['non_synonyms']} "
        f"clusters={s['clusters']} → {args.out}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
