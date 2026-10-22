#!/usr/bin/env python3
"""Cosine-compression evaluation harness for todo embedders.

Re-runnable port of the todo:32ca7662 spike. Takes any ``todo_embed.Embedder``
(``--embedder KEY``) and measures how well its vector space resists the
"compression" failure: every cosine landing in one narrow high band, with
candidate LENGTH outranking topic.

Corpus: the todos' Summary + " " + Body, whole. ``--corpus-before`` pins the
snapshot by ``create_dt`` (default: the 55 oldest todos, the corpus the spike
ran on); ``--corpus-jsonl`` reads ``{"id","c","s","b"}`` lines instead of
shelling out to ``todo.py``.

Candidate domains:
  W  stemmed word 1..3-grams (``todo_search`` stemmer), corpus-wide, freq >= 2
  P  deduped lowercase 1..3-phrase windows (``todo._nphrase_windows``)
  D  the 14 curated labels (6 relevant + 4 distractors + 4 further)

Corrections: ``raw`` cosine; ``centered`` (subtract the corpus mean of the doc
vectors from docs and candidates, renormalize); ``z`` (per-candidate z-score of
its cosines across docs).

Metrics: length bias (spike series), spread (between-label range vs mean
within-label sd), anisotropy (mean pairwise doc cosine; under ``z``, of the docs'
z-score profiles over the domain), hubness (skew of 10-occurrence over the
domain's candidates), precision@1/@3 against gold.

Precision: on D, a hit is a gold curated label in the top k. On W and P it is a
keyword heuristic -- a top-k candidate whose stemmed tokens include a gold keyword
and that does not occur in the subject's own text (self-sourced candidates are
tautological matches).

Embedders that distinguish roles expose ``embed_query`` / ``embed_document``;
candidates and labels are queries, docs are documents, everything else uses
``embed``. Whole-document granularity only.

Run from inside a todo checkout; apple needs ``TODO_APPLE_NLCE_BIN``.
"""

from __future__ import annotations

import argparse
import collections
import json
import math
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import todo_embed
import todo_search

HERE = Path(__file__).resolve().parent

# The 55 oldest todos (by create_dt) are the corpus todo:32ca7662 ran on.
PINNED_CUTOFF = "2026-07-26T01:00:00Z"

CORRECTIONS = ("raw", "centered", "z")
HUBNESS_K = 10

# (text, is_distractor); the spike's 14 curated labels.
CURATED_LABELS: Tuple[Tuple[str, bool], ...] = (
    ("billing and invoicing", True),
    ("command line interface", False),
    ("embedded hardware", False),
    ("git worktrees", False),
    ("semantic tagging", False),
    ("audio file metadata", False),
    ("sqlite storage", False),
    ("automated testing", False),
    ("vector search", False),
    ("user interface design", True),
    ("schema migration", False),
    ("network routing", True),
    ("firmware updates", False),
    ("access control", True),
)

# subject id -> (gold text, accepted curated labels)
GOLD_SUBJECTS: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "515fc9ea": ("automated testing / sqlite storage", ("automated testing", "sqlite storage")),
    "cc756c32": ("git worktrees", ("git worktrees",)),
    "a31d8f24": ("vector search ranking", ("vector search",)),
    "a46c04b0": ("audio (flac) file/directory naming from metadata", ("audio file metadata",)),
    "21e3454c": ("esp32 embedded http endpoints", ("embedded hardware",)),
    "ef4ad78d": ("semantic tagging with embeddings", ("semantic tagging",)),
}

_KEYWORD_STOP = frozenset({"and", "from", "with", "the", "of", "file", "http"})

# Spike series: irrelevant candidate grown word by word vs short relevant ones.
IRRELEVANT_WORDS = (
    "git branch checkout worktree inventory teardown stale "
    "commit push merge rebase origin master"
).split()
IRRELEVANT_LENGTHS = (1, 4, 7, 13)
RELEVANT_CANDIDATES = ("flac", "audio metadata", "flac audio metadata directory naming")
LENGTH_BIAS_TARGET_ID = "a46c04b0"

# Recorded in todo:32ca7662 (apple, 512d); label -> (mean cosine to all docs, sd).
RECORDED_LABELS: Dict[str, Tuple[float, float]] = {
    "billing and invoicing": (0.8138, 0.0174),
    "command line interface": (0.7776, 0.0260),
    "embedded hardware": (0.7685, 0.0207),
    "git worktrees": (0.7428, 0.0211),
    "semantic tagging": (0.7280, 0.0178),
    "audio file metadata": (0.7150, 0.0251),
    "sqlite storage": (0.7140, 0.0310),
    "automated testing": (0.7120, 0.0266),
    "vector search": (0.7090, 0.0301),
    "user interface design": (0.6942, 0.0256),
    "schema migration": (0.6924, 0.0240),
    "network routing": (0.6913, 0.0304),
    "firmware updates": (0.6688, 0.0331),
    "access control": (0.6173, 0.0331),
}
RECORDED_SERIES: Dict[str, float] = {
    "git": 0.476,
    "git branch checkout worktree": 0.832,
    "git branch checkout worktree inventory teardown stale": 0.875,
    "git branch checkout worktree inventory teardown stale commit push merge rebase origin master": 0.895,
    "flac": 0.645,
    "audio metadata": 0.698,
    "flac audio metadata directory naming": 0.916,
}
REPRO_TOLERANCE = 0.01

Vector = List[float]


# --------------------------------------------------------------------------
# Corpus
# --------------------------------------------------------------------------


def doc_text(row: Dict[str, str]) -> str:
    """The whole-document text: Summary and Body joined by a space."""
    return f"{row['s']} {row.get('b', '')}".strip()


def load_corpus_jsonl(path: str, before: Optional[str] = None) -> List[Dict[str, str]]:
    """Read ``{"id","c","s","b"}`` lines, keeping rows created before *before*."""
    rows = []
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return [r for r in rows if before is None or r["c"] < before]


def load_corpus_cli(before: Optional[str] = None) -> List[Dict[str, str]]:
    """Read every todo through ``todo.py`` (cwd selects the repo/store)."""
    todo_py = str(HERE / "todo.py")
    listing = subprocess.run(
        [sys.executable, todo_py, "ls", "-s"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    rows = []
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        proc = subprocess.run(
            [sys.executable, todo_py, "read", parts[1]],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            continue
        rec = json.loads(proc.stdout)
        rows.append(
            {
                "id": rec["Id"][:8],
                "c": rec.get("create_dt", ""),
                "s": (rec.get("Summary") or {}).get("raw", ""),
                "b": (rec.get("Body") or {}).get("raw", ""),
            }
        )
    return [r for r in rows if before is None or r["c"] < before]


# --------------------------------------------------------------------------
# Candidate domains
# --------------------------------------------------------------------------


def word_candidates(texts: Sequence[str], min_freq: int = 2) -> List[str]:
    """Stemmed word 1..3-grams occurring at least *min_freq* times corpus-wide."""
    counts: collections.Counter = collections.Counter()
    for text in texts:
        tokens = todo_search.tokenize(text)
        for n in (1, 2, 3):
            for i in range(len(tokens) - n + 1):
                counts[" ".join(tokens[i : i + n])] += 1
    return sorted(k for k, v in counts.items() if v >= min_freq)


def phrase_candidates(texts: Sequence[str]) -> List[str]:
    """Deduped lowercase 1..3-phrase windows over every text, first-seen order."""
    import todo  # heavy module; only the chunker is needed

    seen: Dict[str, None] = {}
    for text in texts:
        for window in todo._nphrase_windows(text):  # pylint: disable=protected-access
            key = window.strip().lower()
            if key:
                seen.setdefault(key, None)
    return list(seen)


def curated_candidates() -> List[str]:
    return [text for text, _ in CURATED_LABELS]


# --------------------------------------------------------------------------
# Vector helpers
# --------------------------------------------------------------------------


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def unit(v: Sequence[float]) -> Vector:
    norm = math.sqrt(sum(x * x for x in v))
    return [x / norm for x in v] if norm else list(v)


def mean_vector(vectors: Sequence[Sequence[float]]) -> Vector:
    count = len(vectors)
    return [sum(col) / count for col in zip(*vectors)]


def center(v: Sequence[float], mean: Sequence[float]) -> Vector:
    return unit([x - m for x, m in zip(v, mean)])


def skewness(values: Sequence[float]) -> float:
    """Fisher-Pearson moment skewness; 0.0 for a constant sequence."""
    n = len(values)
    if n < 3:
        return 0.0
    mu = sum(values) / n
    m2 = sum((x - mu) ** 2 for x in values) / n
    if m2 == 0.0:
        return 0.0
    m3 = sum((x - mu) ** 3 for x in values) / n
    return m3 / (m2**1.5)


def zscores(values: Sequence[float]) -> List[float]:
    mu = sum(values) / len(values)
    sd = statistics.pstdev(values)
    return [(x - mu) / sd if sd else 0.0 for x in values]


# --------------------------------------------------------------------------
# Embedding with caching and wall-clock
# --------------------------------------------------------------------------


class Space:
    """An embedder plus a cache of unit vectors, role-aware, with timing."""

    def __init__(self, embedder: todo_embed.Embedder) -> None:
        self.embedder = embedder
        self._cache: Dict[Tuple[str, str], Vector] = {}
        self.embed_seconds = 0.0
        self.embed_calls = 0

    def _embed(self, role: str, text: str) -> Vector:
        key = (role, text)
        hit = self._cache.get(key)
        if hit is not None:
            return hit
        fn: Callable[[str], List[float]] = (
            getattr(self.embedder, f"embed_{role}", None) or self.embedder.embed
        )
        start = time.perf_counter()
        vec = unit(fn(text))
        self.embed_seconds += time.perf_counter() - start
        self.embed_calls += 1
        self._cache[key] = vec
        return vec

    def query(self, text: str) -> Vector:
        return self._embed("query", text)

    def document(self, text: str) -> Vector:
        return self._embed("document", text)


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


def correct_scores(
    cand_vecs: Sequence[Vector], doc_vecs: Sequence[Vector], correction: str
) -> List[List[float]]:
    """Score matrix ``S[candidate][doc]`` under one correction."""
    if correction == "centered":
        mean = mean_vector(doc_vecs)
        doc_vecs = [center(d, mean) for d in doc_vecs]
        cand_vecs = [center(c, mean) for c in cand_vecs]
    raw = [[dot(c, d) for d in doc_vecs] for c in cand_vecs]
    if correction == "z":
        return [zscores(row) for row in raw]
    if correction in ("raw", "centered"):
        return raw
    raise ValueError(f"unknown correction {correction!r}")


def anisotropy(
    doc_vecs: Sequence[Vector], scores: Sequence[Sequence[float]], correction: str
) -> float:
    """Mean pairwise cosine of the docs (z: of their z-score profiles)."""
    if correction == "z":
        profiles = [unit([row[j] for row in scores]) for j in range(len(doc_vecs))]
    elif correction == "centered":
        mean = mean_vector(doc_vecs)
        profiles = [center(d, mean) for d in doc_vecs]
    else:
        profiles = list(doc_vecs)
    n = len(profiles)
    total = sum(dot(profiles[i], profiles[j]) for i in range(n) for j in range(i + 1, n))
    return total / (n * (n - 1) / 2)


def hubness(scores: Sequence[Sequence[float]], k: int = HUBNESS_K) -> float:
    """Skew of the k-occurrence of each candidate across the docs' top-k lists."""
    cand_count = len(scores)
    if cand_count == 0:
        return 0.0
    occurrences = [0] * cand_count
    for j in range(len(scores[0])):
        column = [row[j] for row in scores]
        ranked = sorted(zip(column, range(cand_count)), key=lambda pair: (-pair[0], pair[1]))
        ranked = [i for _, i in ranked]
        for i in ranked[:k]:
            occurrences[i] += 1
    return skewness(occurrences)


def label_spread(scores: Sequence[Sequence[float]]) -> Dict[str, Any]:
    """Between-label range of mean score vs mean within-label sd across docs."""
    means = [statistics.fmean(row) for row in scores]
    sds = [statistics.pstdev(row) for row in scores]
    between = max(means) - min(means)
    within = statistics.fmean(sds)
    return {
        "between_range": between,
        "mean_within_sd": within,
        "ratio": (between / within) if within > 1e-12 else None,
        "label_means": means,
        "label_sds": sds,
    }


def _ranked(scores: Sequence[Sequence[float]], doc_index: int, order: Sequence[int]) -> List[int]:
    return sorted(order, key=lambda i: (-scores[i][doc_index], i))


def precision_curated(
    scores: Sequence[Sequence[float]], labels: Sequence[str], subject_index: Dict[str, int]
) -> Dict[str, float]:
    """P@1/@3 on the curated domain: a gold label within the top k."""
    hits = {1: 0, 3: 0}
    order = list(range(len(labels)))
    for sid, (_, accepted) in GOLD_SUBJECTS.items():
        ranked = _ranked(scores, subject_index[sid], order)
        for k in hits:
            if any(labels[i] in accepted for i in ranked[:k]):
                hits[k] += 1
    total = len(GOLD_SUBJECTS)
    return {"p_at_1": hits[1] / total, "p_at_3": hits[3] / total}


def gold_keywords(gold_text: str) -> frozenset:
    return frozenset(t for t in todo_search.tokenize(gold_text) if t not in _KEYWORD_STOP)


def precision_mined(
    scores: Sequence[Sequence[float]],
    candidates: Sequence[str],
    subject_index: Dict[str, int],
    subject_texts: Dict[str, str],
) -> Dict[str, float]:
    """P@1/@3 on a mined domain by gold-keyword overlap, self-sourced excluded."""
    cand_tokens = [frozenset(todo_search.tokenize(c)) for c in candidates]
    hits = {1: 0, 3: 0}
    for sid, (gold_text, _) in GOLD_SUBJECTS.items():
        keywords = gold_keywords(gold_text)
        own = subject_texts[sid].lower()
        pool = [i for i, c in enumerate(candidates) if c not in own]
        ranked = _ranked(scores, subject_index[sid], pool)
        for k in hits:
            if any(cand_tokens[i] & keywords for i in ranked[:k]):
                hits[k] += 1
    total = len(GOLD_SUBJECTS)
    return {"p_at_1": hits[1] / total, "p_at_3": hits[3] / total}


def length_series(
    space: Space, target_vec: Vector, doc_vecs: Sequence[Vector], correction: str
) -> Dict[str, Any]:
    """The spike's length-bias series under one correction."""
    texts = [" ".join(IRRELEVANT_WORDS[:n]) for n in IRRELEVANT_LENGTHS]
    texts += list(RELEVANT_CANDIDATES)
    cand_vecs = [space.query(t) for t in texts]
    if correction == "centered":
        mean = mean_vector(doc_vecs)
        target = center(target_vec, mean)
        cand_vecs = [center(c, mean) for c in cand_vecs]
        values = [dot(c, target) for c in cand_vecs]
    elif correction == "z":
        values = []
        for c in cand_vecs:
            across = [dot(c, d) for d in doc_vecs]
            mu, sd = statistics.fmean(across), statistics.pstdev(across)
            values.append(((dot(c, target_vec) - mu) / sd) if sd else 0.0)
    else:
        values = [dot(c, target_vec) for c in cand_vecs]
    series = dict(zip(texts, values))
    irrelevant_longest = series[texts[len(IRRELEVANT_LENGTHS) - 1]]
    relevant_two_word = series["audio metadata"]
    return {
        "series": series,
        "inverted": relevant_two_word > irrelevant_longest,
        "relevant_2w_minus_irrelevant_13w": relevant_two_word - irrelevant_longest,
    }


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def evaluate(
    embedder: todo_embed.Embedder,
    rows: Sequence[Dict[str, str]],
    domains: Sequence[str] = ("W", "P", "D"),
    corrections: Sequence[str] = CORRECTIONS,
) -> Dict[str, Any]:
    """Run every (domain x correction) cell; return a JSON-serializable report."""
    started = time.perf_counter()
    space = Space(embedder)
    texts = [doc_text(r) for r in rows]
    ids = [r["id"] for r in rows]
    doc_vecs = [space.document(t) for t in texts]
    subject_index = {sid: ids.index(sid) for sid in GOLD_SUBJECTS if sid in ids}
    missing = sorted(set(GOLD_SUBJECTS) - set(subject_index))
    if missing:
        raise ValueError(f"gold subjects missing from corpus: {missing}")
    subject_texts = {sid: texts[i] for sid, i in subject_index.items()}

    candidate_sets: Dict[str, List[str]] = {}
    for name in domains:
        if name == "W":
            candidate_sets[name] = word_candidates(texts)
        elif name == "P":
            candidate_sets[name] = phrase_candidates(texts)
        elif name == "D":
            candidate_sets[name] = curated_candidates()
        else:
            raise ValueError(f"unknown domain {name!r}")

    labels = curated_candidates()
    label_vecs = [space.query(t) for t in labels]
    report: Dict[str, Any] = {
        "fingerprint": embedder.fingerprint(),
        "dim": embedder.dimension(),
        "docs": len(rows),
        "domain_sizes": {k: len(v) for k, v in candidate_sets.items()},
        "length_bias": {},
        "cells": [],
    }
    target_id = LENGTH_BIAS_TARGET_ID
    target_vec = doc_vecs[ids.index(target_id)] if target_id in ids else None
    for corr in corrections:
        if target_vec is not None:
            report["length_bias"][corr] = length_series(space, target_vec, doc_vecs, corr)
        label_scores = correct_scores(label_vecs, doc_vecs, corr)
        spread = label_spread(label_scores)
        for name, cands in candidate_sets.items():
            cand_vecs = [space.query(c) for c in cands]
            scores = correct_scores(cand_vecs, doc_vecs, corr)
            if name == "D":
                prec = precision_curated(scores, cands, subject_index)
            else:
                prec = precision_mined(scores, cands, subject_index, subject_texts)
            report["cells"].append(
                {
                    "domain": name,
                    "correction": corr,
                    "spread_range": spread["between_range"],
                    "spread_within_sd": spread["mean_within_sd"],
                    "spread_ratio": spread["ratio"],
                    "anisotropy": anisotropy(doc_vecs, scores, corr),
                    "hubness_skew": hubness(scores),
                    "p_at_1": prec["p_at_1"],
                    "p_at_3": prec["p_at_3"],
                }
            )
    report["raw_label_table"] = label_table(label_vecs, doc_vecs, labels)
    report["embed_seconds"] = space.embed_seconds
    report["embed_calls"] = space.embed_calls
    report["wall_seconds"] = time.perf_counter() - started
    return report


def label_table(
    label_vecs: Sequence[Vector], doc_vecs: Sequence[Vector], labels: Sequence[str]
) -> List[Dict[str, Any]]:
    """Per label: mean raw cosine to all docs and sd across docs."""
    out = []
    for label, vec in zip(labels, label_vecs):
        row = [dot(vec, d) for d in doc_vecs]
        out.append({"label": label, "mean": statistics.fmean(row), "sd": statistics.pstdev(row)})
    return out


def reproduction_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Compare the raw label table and length series with todo:32ca7662's record."""
    rows = []
    for entry in report["raw_label_table"]:
        want_mean, want_sd = RECORDED_LABELS[entry["label"]]
        rows.append(
            {
                "what": f"label mean: {entry['label']}",
                "recorded": want_mean,
                "measured": entry["mean"],
                "delta": entry["mean"] - want_mean,
            }
        )
        rows.append(
            {
                "what": f"label sd: {entry['label']}",
                "recorded": want_sd,
                "measured": entry["sd"],
                "delta": entry["sd"] - want_sd,
            }
        )
    series = report["length_bias"].get("raw", {}).get("series", {})
    for text, want in RECORDED_SERIES.items():
        if text in series:
            rows.append(
                {
                    "what": f"length series: {text!r}",
                    "recorded": want,
                    "measured": series[text],
                    "delta": series[text] - want,
                }
            )
    for row in rows:
        row["within_tolerance"] = abs(row["delta"]) <= REPRO_TOLERANCE
    return rows


def format_report(report: Dict[str, Any]) -> str:
    lines = [
        f"embedder {report['fingerprint']} dim={report['dim']} docs={report['docs']}",
        f"domain sizes {report['domain_sizes']}",
        f"embed wall-clock {report['embed_seconds']:.1f}s over {report['embed_calls']} texts; "
        f"total {report['wall_seconds']:.1f}s",
        "",
        "domain correction spread_range within_sd ratio anisotropy hubness_skew p@1 p@3",
    ]
    for c in report["cells"]:
        ratio = "n/a" if c["spread_ratio"] is None else f"{c['spread_ratio']:.2f}"
        lines.append(
            f"{c['domain']:>6} {c['correction']:>10} {c['spread_range']:.4f} "
            f"{c['spread_within_sd']:.4f} {ratio:>6} {c['anisotropy']:.4f} "
            f"{c['hubness_skew']:.3f} {c['p_at_1']:.2f} {c['p_at_3']:.2f}"
        )
    lines.append("")
    for corr, lb in report["length_bias"].items():
        lines.append(f"length bias [{corr}] inverted={lb['inverted']}")
        for text, value in lb["series"].items():
            lines.append(f"  {value:+.4f}  {text}")
    return "\n".join(lines)


def format_reproduction(rows: Sequence[Dict[str, Any]]) -> str:
    lines = ["reproduction vs todo:32ca7662 (tolerance +-%.2f)" % REPRO_TOLERANCE]
    for row in rows:
        flag = "ok  " if row["within_tolerance"] else "MISS"
        lines.append(
            f"  {flag} {row['what']}: recorded {row['recorded']:.4f} "
            f"measured {row['measured']:.4f} delta {row['delta']:+.4f}"
        )
    passed = sum(1 for r in rows if r["within_tolerance"])
    lines.append(f"  {passed} of {len(rows)} within tolerance")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    ap.add_argument("--embedder", default="apple", help="todo_embed selection key")
    ap.add_argument("--corpus-jsonl", help="JSONL snapshot instead of todo.py")
    ap.add_argument("--corpus-before", default=PINNED_CUTOFF, help="create_dt cutoff")
    ap.add_argument("--domains", default="W,P,D")
    ap.add_argument("--corrections", default=",".join(CORRECTIONS))
    ap.add_argument("--repro", action="store_true", help="also compare with todo:32ca7662")
    ap.add_argument("--json", dest="json_out", help="write the full report here")
    args = ap.parse_args(argv)

    rows = (
        load_corpus_jsonl(args.corpus_jsonl, args.corpus_before)
        if args.corpus_jsonl
        else load_corpus_cli(args.corpus_before)
    )
    embedder = todo_embed.get_embedder(args.embedder)
    report = evaluate(
        embedder,
        rows,
        domains=args.domains.split(","),
        corrections=args.corrections.split(","),
    )
    print(format_report(report))
    if args.repro:
        repro = reproduction_rows(report)
        report["reproduction"] = repro
        print()
        print(format_reproduction(repro))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=1)
    return 0


if __name__ == "__main__":
    os.environ.setdefault("PYTHONHASHSEED", "0")
    sys.exit(main())
