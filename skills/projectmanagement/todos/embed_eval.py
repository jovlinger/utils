#!/usr/bin/env python3
"""Re-runnable embedder evaluation harness (port of the todo:32ca7662 spike).

Takes any ``todo_embed.Embedder`` and measures how its vector space behaves on
the todo corpus: whether cosine ranks candidate LENGTH over topic, how far label
scores spread, anisotropy, hubness, and precision against the curated gold set.

Each measurement is reported raw, mean-centered (corpus mean subtracted from
every vector, then renormalized) and per-candidate z-scored over the corpus.

Corpus: todos loaded through ``todo._load_corpus``. ``--max-create-dt`` cuts the
corpus by ``create_dt`` (ISO string, exclusive). The spike ran on 55 todos that
cannot be reconstructed exactly; the default cut keeps the 59 todos created
before 2026-08-06, which is the closest prefix of the store.

Document text is ``Summary.raw + Body.raw`` (no separator), the same string
whose length the spike reported.

Usage (from the todos directory, with the store reachable from cwd):

  python3 embed_eval.py --embedder apple
  python3 embed_eval.py --embedder apple --domains W --json out.json
"""

from __future__ import annotations

import argparse
import itertools
import json
import operator
import statistics
import sys
import time
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

import todo
import todo_embed
import todo_search
import todo_store
from todo_embed import Embedder

# Spike subjects: 8-char todo prefix -> set of acceptable gold labels.
# 21e3454c's gold text in the spike was "esp32 embedded http endpoints"; the
# curated label closest to it is "embedded hardware".
SUBJECTS: Dict[str, Tuple[str, ...]] = {
    "515fc9ea": ("sqlite storage", "automated testing"),
    "cc756c32": ("git worktrees",),
    "a31d8f24": ("vector search",),
    "a46c04b0": ("audio file metadata",),
    "21e3454c": ("embedded hardware",),
    "ef4ad78d": ("semantic tagging",),
}

# Spike's 14 curated labels: 10 real, 4 distractors.
LABELS: Tuple[str, ...] = (
    "billing and invoicing",
    "command line interface",
    "embedded hardware",
    "git worktrees",
    "semantic tagging",
    "audio file metadata",
    "sqlite storage",
    "automated testing",
    "vector search",
    "user interface design",
    "schema migration",
    "network routing",
    "firmware updates",
    "access control",
)
DISTRACTORS: Tuple[str, ...] = (
    "billing and invoicing",
    "user interface design",
    "network routing",
    "access control",
)

# Length-bias series from the spike. The irrelevant candidate grows word by word.
IRRELEVANT: Tuple[str, ...] = (
    "git",
    "git branch checkout worktree",
    "git branch checkout worktree inventory teardown stale",
    "git branch checkout worktree inventory teardown stale commit push merge rebase origin master",
)
RELEVANT: Tuple[str, ...] = (
    "flac",
    "audio metadata",
    "flac audio metadata directory naming",
)
# The spike names its fixed target only as "flac/audio metadata".
DEFAULT_LENGTH_TARGET = "flac/audio metadata"

CORRECTIONS: Tuple[str, ...] = ("raw", "centered", "z")
# z is omitted from the label table: each label's z-scores over the docs have
# mean 0 and sd 1 by construction, so its spread is 0 and says nothing.
LABEL_CORRECTIONS: Tuple[str, ...] = ("raw", "centered")
DEFAULT_MAX_CREATE_DT = "2026-08-06"
K_HUB = 10


# -- vectors -----------------------------------------------------------------


def _unit(vec: Sequence[float]) -> List[float]:
    norm = sum(x * x for x in vec) ** 0.5
    return list(vec) if norm == 0.0 else [x / norm for x in vec]


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    """Dot product; for unit vectors this is the cosine."""
    return sum(map(operator.mul, a, b))


class Vectors:
    """Embeds through an Embedder once per distinct text, returns unit vectors.

    Identity of the returned list is stable per text, so it can key caches.
    """

    def __init__(self, embedder: Embedder) -> None:
        self._embedder = embedder
        self._cache: Dict[str, List[float]] = {}
        self.seconds = 0.0
        self.embeds = 0

    def __call__(self, text: str) -> List[float]:
        hit = self._cache.get(text)
        if hit is None:
            start = time.perf_counter()
            hit = _unit(self._embedder.embed(text))
            self.seconds += time.perf_counter() - start
            self.embeds += 1
            self._cache[text] = hit
        return hit


def mean_vector(vectors: Sequence[Sequence[float]]) -> List[float]:
    dim = len(vectors[0])
    total = [0.0] * dim
    for vec in vectors:
        for i, x in enumerate(vec):
            total[i] += x
    return [x / len(vectors) for x in total]


class Scorer:
    """Scores candidates against subjects under one correction.

    A vector is handled as a pair ``(raw, prepared)``: ``raw`` is the unit
    embedding, ``prepared`` is what the correction compares (the same as
    ``raw`` except under ``centered``). Subject chunks score by MAX.

    ``z`` is the per-candidate z-score of its raw cosine over the whole-doc
    vectors, so a candidate's own offset and spread are removed.
    """

    def __init__(self, correction: str, doc_vectors: Sequence[Sequence[float]]) -> None:
        if correction not in CORRECTIONS:
            raise ValueError(f"unknown correction {correction!r}")
        self.correction = correction
        self._docs = list(doc_vectors)
        self._mean = mean_vector(self._docs) if correction == "centered" else None
        self._stats: Dict[int, Tuple[float, float]] = {}

    def pair(self, raw: Sequence[float]) -> Tuple[Sequence[float], Sequence[float]]:
        if self.correction == "centered":
            assert self._mean is not None
            return raw, _unit([x - m for x, m in zip(raw, self._mean)])
        return raw, raw

    def _zstats(self, raw: Sequence[float]) -> Tuple[float, float]:
        key = id(raw)
        if key not in self._stats:
            sims = [dot(raw, d) for d in self._docs]
            sd = statistics.pstdev(sims)
            self._stats[key] = (statistics.fmean(sims), sd if sd > 0 else 1.0)
        return self._stats[key]

    def score(self, cand: Tuple, subjects: Sequence[Tuple]) -> float:
        if self.correction == "z":
            mu, sd = self._zstats(cand[0])
            best = max(dot(cand[0], s[0]) for s in subjects)
            return (best - mu) / sd
        return max(dot(cand[1], s[1]) for s in subjects)


def _pairs(scorer: Scorer, raws: Iterable[Sequence[float]]) -> List[Tuple]:
    return [scorer.pair(r) for r in raws]


# -- metrics -----------------------------------------------------------------


def length_series(vec: Vectors, target: str, docs: Sequence[Sequence[float]]) -> List[dict]:
    """Irrelevant-grown and relevant candidates scored against one fixed target."""
    rows = []
    for kind, texts in (("irrelevant", IRRELEVANT), ("relevant", RELEVANT)):
        for text in texts:
            row = {"kind": kind, "text": text, "words": len(text.split())}
            for c in CORRECTIONS:
                scorer = Scorer(c, docs)
                row[c] = round(scorer.score(scorer.pair(vec(text)), [scorer.pair(vec(target))]), 4)
            rows.append(row)
    return rows


def label_table(vec: Vectors, docs: Sequence[Sequence[float]], correction: str) -> List[dict]:
    """Per label: mean and sample sd of its score across the whole-doc vectors."""
    scorer = Scorer(correction, docs)
    doc_pairs = _pairs(scorer, docs)
    rows = []
    for label in LABELS:
        lpair = scorer.pair(vec(label))
        sims = [scorer.score(lpair, [d]) for d in doc_pairs]
        rows.append(
            {
                "label": label,
                "distractor": label in DISTRACTORS,
                "mean": round(statistics.fmean(sims), 4),
                "sd": round(statistics.stdev(sims), 4),
            }
        )
    return rows


def spread_ratio(table: Sequence[dict]) -> float:
    """Between-label range of the means divided by the mean within-label sd."""
    means = [r["mean"] for r in table]
    sds = [r["sd"] for r in table]
    return round((max(means) - min(means)) / statistics.fmean(sds), 3)


def anisotropy(docs: Sequence[Sequence[float]]) -> float:
    pairs = list(itertools.combinations(docs, 2))
    return round(statistics.fmean(dot(a, b) for a, b in pairs), 4)


def hubness_skew(docs: Sequence[Sequence[float]], k: int = K_HUB) -> float:
    """Third standardized moment of k-occurrence counts over the doc vectors."""
    n = len(docs)
    occurrences = [0] * n
    for i in range(n):
        sims = sorted(
            ((dot(docs[i], docs[j]), j) for j in range(n) if j != i),
            key=lambda t: (-t[0], t[1]),
        )
        for _, j in sims[:k]:
            occurrences[j] += 1
    mu = statistics.fmean(occurrences)
    m2 = statistics.fmean((x - mu) ** 2 for x in occurrences)
    m3 = statistics.fmean((x - mu) ** 3 for x in occurrences)
    return round(m3 / (m2**1.5), 4) if m2 > 0 else 0.0


def _is_hit(candidate: str, gold: Sequence[str]) -> bool:
    """A candidate hits when its stemmed tokens contain a gold label's stemmed tokens."""
    got = set(todo_search.tokenize(candidate))
    return any(set(todo_search.tokenize(g)) <= got for g in gold)


def _subject_pairs(
    scorer: Scorer, subject_chunks: Dict[str, Sequence[Sequence[float]]]
) -> Dict[str, List[Tuple]]:
    return {p: _pairs(scorer, chunks) for p, chunks in subject_chunks.items()}


def precision_for_domain(
    vec: Vectors,
    correction: str,
    doc_vecs: Sequence[Sequence[float]],
    candidates: Sequence[str],
    subject_chunks: Dict[str, Sequence[Sequence[float]]],
    subject_text: Dict[str, str],
) -> dict:
    """Precision@1 (count of six subjects) and mean precision@3 for a candidate domain."""
    scorer = Scorer(correction, doc_vecs)
    subj = _subject_pairs(scorer, subject_chunks)
    cand_pairs = [(c, scorer.pair(vec(c))) for c in candidates]
    hits1 = 0
    p3s = []
    self_rank1 = 0
    detail = []
    for prefix, gold in SUBJECTS.items():
        scores = [(c, scorer.score(cp, subj[prefix])) for c, cp in cand_pairs]
        ranked = sorted(scores, key=lambda t: (-t[1], t[0]))
        top1 = _is_hit(ranked[0][0], gold)
        p3 = sum(1 for text, _ in ranked[:3] if _is_hit(text, gold)) / 3.0
        if ranked[0][0].lower() in subject_text[prefix].lower():
            self_rank1 += 1
        hits1 += int(top1)
        p3s.append(p3)
        detail.append({"subject": prefix, "top1": ranked[0][0], "hit1": top1})
    return {
        "precision_at_1": f"{hits1}/{len(SUBJECTS)}",
        "precision_at_3": round(statistics.fmean(p3s), 4),
        "self_sourced_rank1": self_rank1,
        "detail": detail,
    }


def subject_domain_precision(
    vec: Vectors,
    correction: str,
    doc_vecs: Sequence[Sequence[float]],
    subject_chunks: Dict[str, Sequence[Sequence[float]]],
) -> dict:
    """Precision over the curated label domain D (a hit is an exact gold label)."""
    scorer = Scorer(correction, doc_vecs)
    subj = _subject_pairs(scorer, subject_chunks)
    label_pairs = [(lab, scorer.pair(vec(lab))) for lab in LABELS]
    hits1 = 0
    p3s = []
    detail = []
    for prefix, gold in SUBJECTS.items():
        scores = [(lab, scorer.score(lp, subj[prefix])) for lab, lp in label_pairs]
        ranked = sorted(scores, key=lambda t: (-t[1], t[0]))
        top1 = ranked[0][0] in gold
        p3 = sum(1 for lab, _ in ranked[:3] if lab in gold) / 3.0
        hits1 += int(top1)
        p3s.append(p3)
        detail.append({"subject": prefix, "top1": ranked[0][0], "hit1": top1})
    return {
        "precision_at_1": f"{hits1}/{len(SUBJECTS)}",
        "precision_at_3": round(statistics.fmean(p3s), 4),
        "detail": detail,
    }


# -- corpus ------------------------------------------------------------------


def load_documents(max_create_dt: Optional[str]) -> Tuple[List[str], Dict[str, str]]:
    """(doc ids, id -> whole text) for todos created before *max_create_dt*."""
    store = todo_store.get_store()
    tickets, raws = todo._load_corpus(store)
    ids = []
    texts: Dict[str, str] = {}
    for tid in sorted(tickets):
        created = str(tickets[tid].get("create_dt", ""))
        if max_create_dt is not None and created >= max_create_dt:
            continue
        whole = raws[tid].get("Summary.raw", "") + raws[tid].get("Body.raw", "")
        if not whole.strip():
            continue
        ids.append(tid)
        texts[tid] = whole
    return ids, texts


def word_ngram_candidates(texts: Iterable[str], min_df: int = 2) -> List[str]:
    """Stemmed word 1..3-grams (todo_search stemmer) with document frequency >= min_df."""
    df: Dict[str, int] = {}
    for text in texts:
        toks = todo_search.tokenize(text)
        grams: Set[str] = set()
        for n in (1, 2, 3):
            for i in range(len(toks) - n + 1):
                grams.add(" ".join(toks[i : i + n]))
        for g in grams:
            df[g] = df.get(g, 0) + 1
    return sorted(g for g, count in df.items() if count >= min_df)


def phrase_candidates(texts: Iterable[str]) -> List[str]:
    """Deduped, downcased 1..3-phrase windows: the shipped tag candidate domain."""
    return todo._mine_tag_candidates({i: {"Summary.raw": t} for i, t in enumerate(texts)})


# -- run ---------------------------------------------------------------------


def run(
    embedder: Embedder,
    *,
    max_create_dt: Optional[str] = DEFAULT_MAX_CREATE_DT,
    domains: Sequence[str] = ("W", "P"),
    length_target: str = DEFAULT_LENGTH_TARGET,
) -> dict:
    """Evaluate *embedder* and return a JSON-serializable result dict."""
    vec = Vectors(embedder)
    ids, texts = load_documents(max_create_dt)
    if not ids:
        raise RuntimeError("no todos in the corpus; check the store and --max-create-dt")
    start = time.perf_counter()
    doc_vecs = [vec(texts[i]) for i in ids]
    doc_embed_seconds = round(time.perf_counter() - start, 2)

    subject_ids = {}
    for prefix in SUBJECTS:
        matches = [i for i in ids if i.startswith(prefix)]
        if len(matches) != 1:
            raise RuntimeError(f"subject {prefix} matched {len(matches)} todos in the corpus")
        subject_ids[prefix] = matches[0]
    subject_text = {p: texts[i] for p, i in subject_ids.items()}
    subject_whole = {p: [vec(t)] for p, t in subject_text.items()}
    subject_chunks = {
        p: [vec(c) for c in todo._nphrase_windows(t)] for p, t in subject_text.items()
    }
    all_texts = [texts[i] for i in ids]
    result: dict = {
        "embedder": {
            "fingerprint": embedder.fingerprint(),
            "dimension": embedder.dimension(),
        },
        "corpus": {"documents": len(ids), "max_create_dt": max_create_dt},
        "length_target": length_target,
        "length_series": length_series(vec, length_target, doc_vecs),
        "labels": {},
        "anisotropy": {
            "raw": anisotropy(doc_vecs),
            "centered": anisotropy(
                [_unit([x - m for x, m in zip(d, mean_vector(doc_vecs))]) for d in doc_vecs]
            ),
        },
        "hubness_skew": hubness_skew(doc_vecs),
        "domains": {"D": {}},
        "timing": {"doc_embed_seconds": doc_embed_seconds},
    }
    for c in LABEL_CORRECTIONS:
        table = label_table(vec, doc_vecs, c)
        result["labels"][c] = {"table": table, "spread": spread_ratio(table)}
    for c in CORRECTIONS:
        for mode, subj in (("whole", subject_whole), ("chunk", subject_chunks)):
            result["domains"]["D"].setdefault(mode, {})[c] = subject_domain_precision(
                vec, c, doc_vecs, subj
            )

    candidate_sets: Dict[str, List[str]] = {}
    if "W" in domains:
        candidate_sets["W"] = word_ngram_candidates(all_texts)
    if "P" in domains:
        candidate_sets["P"] = phrase_candidates(all_texts)
    for name, cands in candidate_sets.items():
        result["domains"][name] = {"candidates": len(cands)}
        for c in CORRECTIONS:
            result["domains"][name][c] = precision_for_domain(
                vec, c, doc_vecs, cands, subject_chunks, subject_text
            )
    result["timing"]["total_embeds"] = vec.embeds
    result["timing"]["embed_seconds"] = round(vec.seconds, 2)
    return result


def _print_report(result: dict) -> None:
    print(f"embedder {result['embedder']['fingerprint']} dim={result['embedder']['dimension']}")
    print(
        f"corpus documents={result['corpus']['documents']} (create_dt < {result['corpus']['max_create_dt']})"
    )
    print(f"length target: {result['length_target']!r}")
    for row in result["length_series"]:
        print(
            f"  {row['kind']:<10} words={row['words']:<3} raw={row['raw']:+.4f} "
            f"centered={row['centered']:+.4f} z={row['z']:+.4f}  {row['text']}"
        )
    print("label table (raw): label, mean, sd")
    for row in result["labels"]["raw"]["table"]:
        print(
            f"  {row['label']:<24} {row['mean']:.4f} {row['sd']:.4f}"
            f"{'  distractor' if row['distractor'] else ''}"
        )
    print(
        f"spread raw={result['labels']['raw']['spread']} centered={result['labels']['centered']['spread']}"
    )
    print(
        f"anisotropy raw={result['anisotropy']['raw']} centered={result['anisotropy']['centered']}"
    )
    print(f"hubness skew (k={K_HUB})={result['hubness_skew']}")
    for mode, per_corr in result["domains"]["D"].items():
        for c in CORRECTIONS:
            p = per_corr[c]
            print(f"domain D ({mode}) {c}: p@1={p['precision_at_1']} p@3={p['precision_at_3']}")
    for name in ("W", "P"):
        if name not in result["domains"]:
            continue
        print(f"domain {name}: {result['domains'][name]['candidates']} candidates")
        for c in CORRECTIONS:
            p = result["domains"][name][c]
            print(
                f"  {name} {c}: p@1={p['precision_at_1']} p@3={p['precision_at_3']}"
                f" self-sourced rank1={p['self_sourced_rank1']}"
            )
    print(f"timing: {result['timing']}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--embedder", required=True, help="selection key from todo_embed")
    parser.add_argument(
        "--max-create-dt",
        default=DEFAULT_MAX_CREATE_DT,
        help="exclude todos created at or after this ISO time; '' for all",
    )
    parser.add_argument("--domains", default="W,P", help="comma list of W,P")
    parser.add_argument("--length-target", default=DEFAULT_LENGTH_TARGET)
    parser.add_argument("--json", dest="json_path", help="also write the full result here")
    args = parser.parse_args(argv)
    embedder = todo_embed.get_embedder(args.embedder)
    result = run(
        embedder,
        max_create_dt=args.max_create_dt or None,
        domains=[d.strip() for d in args.domains.split(",") if d.strip()],
        length_target=args.length_target,
    )
    _print_report(result)
    if args.json_path:
        with open(args.json_path, "w", encoding="ascii") as handle:
            json.dump(result, handle, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
