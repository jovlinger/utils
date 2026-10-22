#!/usr/bin/env python3
"""Embedder compression eval: the todo:32ca7662 experiment as a re-runnable harness.

Runs any registered ``todo_embed`` Embedder over the todo corpus and reports how
compressed its cosine space is, so embedders can be compared on the same
numbers. One invocation embeds everything once and evaluates every
(domain x correction) cell from those vectors.

Corpus: every todo in the store, one document per todo, Summary and Body joined
with a single space (exactly what the shipped auto-tagger embeds).
``--as-of <iso>`` keeps only todos whose ``update_dt`` is at or before that
instant, ``--include``/``--exclude`` add or drop Id prefixes. The closest
rebuild of the 55-document corpus the spike ran on is
``--as-of 2026-08-05T13:25:29Z --exclude 32ca7662 --include 21e3454c`` (the
spike's own record dropped; 21e3454c, a subject, was edited after the spike).

Candidate domains:

``W``  stemmed word 1..3-grams (``todo_search.tokenize``), never crossing a
       document boundary, kept when the n-gram occurs >= 2 times corpus-wide.
``P``  1..3-phrase windows (the shipped ``todo._nphrase_windows`` chunker) over
       each Summary and Body, downcased and stripped, deduped.
``L``  the 14 curated labels (10 real, 4 distractors).

Corrections:

``raw``       cosine.
``centered``  subtract the mean document vector from every vector (documents,
              chunks and candidates alike), renormalize, then cosine.
``z``         per-candidate z-score of the raw cosine across all documents.

Metrics:

``length_bias``  the spike series: an irrelevant candidate grown 1/4/7/13 words
                 and three relevant ones, scored against the a46c04b0 (flac
                 directory names) document. ``inversion_margin`` is
                 score("audio metadata") - score(13-word irrelevant); it must be
                 positive for the space to rank topic over length.
``spread``       per-candidate mean and population sd of score across documents.
                 ``range`` = max - min of the means; ``between_sd`` = sd of the
                 means; ``within_sd`` = mean of the per-candidate sds;
                 ``signal_ratio`` = within_sd / between_sd (how much WHICH
                 document is scored moves a number, relative to the candidate's
                 fixed offset; higher is better).
``anisotropy``   mean pairwise cosine over all document vectors (raw and
                 centered only; z is not a vector space).
``hubness``      skewness of k-occurrence: for each document, its top-k
                 candidates; N_k(c) counts how many documents list c.
``precision``    over the 6 gold subjects: ``p_at_1``, ``p_at_3`` (hits in the
                 top 3 / 3) and ``hit_at_3`` (any hit in the top 3). In ``L`` a hit
                 is a gold label; in ``W`` and ``P`` it is a candidate sharing a
                 stemmed token with the subject's ``GOLD_TERMS``. ``P`` excludes
                 candidates mined from the subject itself (they match their own
                 sentence verbatim and are tautological).

``--granularity chunk`` scores a candidate against a document as the max over
that document's 1..3-phrase windows instead of one whole-document vector. Pure
Python: expect it to cost minutes per domain, not seconds.

``--check-spike`` (raw, whole granularity) prints each recorded todo:32ca7662
apple number next to the measured one with the delta.

Usage::

    ./embed_eval.py --embedder apple --as-of 2026-08-05T13:25:29Z \
        --exclude 32ca7662 --include 21e3454c --check-spike
    ./embed_eval.py --embedder st --out results.json
"""

from __future__ import annotations

import argparse
import json
import math
import operator
import statistics
import sys
import time
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Set, Tuple

import todo_embed
import todo_search

Vector = List[float]

DOMAINS: Tuple[str, ...] = ("W", "P", "L")
CORRECTIONS: Tuple[str, ...] = ("raw", "centered", "z")
HUBNESS_K = 10
WORD_NGRAM_MAX = 3
WORD_MIN_FREQ = 2

# The 14 curated labels of todo:32ca7662, in its table order.
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

# Gold subjects (todo id prefix -> gold labels in LABELS). Stated up front so a
# result can be rechecked. The spike counted both labels as correct for
# 515fc9ea and ef4ad78d.
SUBJECTS: Dict[str, Tuple[str, ...]] = {
    "515fc9ea": ("automated testing", "sqlite storage"),
    "cc756c32": ("git worktrees",),
    "a31d8f24": ("vector search",),
    "a46c04b0": ("audio file metadata",),
    "21e3454c": ("embedded hardware",),
    "ef4ad78d": ("semantic tagging", "vector search"),
}

# Gold terms per subject, judging mined W / P candidates: a candidate is a hit
# when its stemmed tokens intersect the subject's stemmed gold terms.
GOLD_WORDS: Dict[str, str] = {
    "515fc9ea": "test testing sqlite storage",
    "cc756c32": "git worktree worktrees",
    "a31d8f24": "vector vec search ranking",
    "a46c04b0": "flac audio metadata",
    "21e3454c": "esp32 embedded http endpoint endpoints healthz",
    "ef4ad78d": "semantic tag tagging embed embedding embeddings",
}
GOLD_TERMS: Dict[str, frozenset] = {
    subject: frozenset(todo_search.tokenize(words)) for subject, words in GOLD_WORDS.items()
}

LENGTH_TARGET = "a46c04b0"
LENGTH_IRRELEVANT: Tuple[str, ...] = (
    "git",
    "git branch checkout worktree",
    "git branch checkout worktree inventory teardown stale",
    "git branch checkout worktree inventory teardown stale commit push merge rebase origin master",
)
LENGTH_RELEVANT: Tuple[str, ...] = (
    "flac",
    "audio metadata",
    "flac audio metadata directory naming",
)

# todo:32ca7662 apple numbers (Body, EVIDENCE items 1 and 2).
SPIKE_AS_OF = "2026-08-05T13:25:29Z"
SPIKE_LENGTH_SERIES: Dict[str, float] = dict(
    zip(LENGTH_IRRELEVANT + LENGTH_RELEVANT, (0.476, 0.832, 0.875, 0.895, 0.645, 0.698, 0.916))
)
SPIKE_LABEL_TABLE: Dict[str, Tuple[float, float]] = {
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


class Doc:
    """One corpus document: a todo's Summary+Body, plus its fields for mining."""

    def __init__(self, doc_id: str, summary: str, body: str) -> None:
        self.doc_id = doc_id
        self.fields = [raw for raw in (summary, body) if raw]
        self.text = " ".join(self.fields)

    def chunks(self) -> List[str]:
        """1..3-phrase windows over each field (the shipped chunker)."""
        import todo  # pylint: disable=import-outside-toplevel

        windows: List[str] = []
        for raw in self.fields:
            windows.extend(todo._nphrase_windows(raw))  # pylint: disable=protected-access
        return windows or [self.text]


def load_corpus(
    as_of: Optional[str] = None,
    *,
    include: Sequence[str] = (),
    exclude: Sequence[str] = (),
) -> List[Doc]:
    """Every todo in the store as a Doc.

    *as_of* keeps only todos with ``update_dt <= as_of``; an Id starting with a
    prefix in *include* is kept regardless of *as_of*; one starting with a
    prefix in *exclude* is always dropped.
    """
    import todo  # pylint: disable=import-outside-toplevel
    import todo_store  # pylint: disable=import-outside-toplevel

    docs: List[Doc] = []
    for parsed in todo_store.get_store().list_all():
        if not isinstance(parsed, dict) or not parsed.get("Id"):
            continue
        ticket_id = str(parsed["Id"])
        if any(ticket_id.startswith(p) for p in exclude):
            continue
        late = as_of is not None and str(parsed.get("update_dt", "")) > as_of
        if late and not any(ticket_id.startswith(p) for p in include):
            continue
        summary = todo._raw_of(parsed, "Summary") or ""  # pylint: disable=protected-access
        body = todo._raw_of(parsed, "Body") or ""  # pylint: disable=protected-access
        if summary or body:
            docs.append(Doc(ticket_id, summary, body))
    docs.sort(key=lambda d: d.doc_id)
    return docs


def word_domain(docs: Sequence[Doc]) -> List[str]:
    """Domain W: stemmed word 1..3-grams occurring >= WORD_MIN_FREQ times corpus-wide."""
    counts: Dict[str, int] = {}
    for doc in docs:
        tokens = todo_search.tokenize(doc.text)
        for n in range(1, WORD_NGRAM_MAX + 1):
            for i in range(len(tokens) - n + 1):
                gram = " ".join(tokens[i : i + n])
                counts[gram] = counts.get(gram, 0) + 1
    return sorted(gram for gram, count in counts.items() if count >= WORD_MIN_FREQ)


def phrase_domain(
    docs: Sequence[Doc], windows: Callable[[str], List[str]]
) -> Tuple[List[str], Dict[str, Set[str]]]:
    """Domain P: deduped downcased phrase windows, and which docs each came from."""
    sources: Dict[str, Set[str]] = {}
    order: List[str] = []
    for doc in docs:
        for raw in doc.fields:
            for window in windows(raw):
                candidate = window.strip().lower()
                if not candidate:
                    continue
                if candidate not in sources:
                    sources[candidate] = set()
                    order.append(candidate)
                sources[candidate].add(doc.doc_id)
    return order, sources


def _default_windows(raw: str) -> List[str]:
    import todo  # pylint: disable=import-outside-toplevel

    return todo._nphrase_windows(raw)  # pylint: disable=protected-access


def normalize(vec: Sequence[float]) -> Vector:
    """l2-normalize; a zero vector stays zero."""
    norm = math.sqrt(sum(v * v for v in vec))
    return list(vec) if norm == 0.0 else [v / norm for v in vec]


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    """Dot product (cosine for unit vectors)."""
    return sum(map(operator.mul, a, b))


def mean_vector(vectors: Sequence[Sequence[float]]) -> Vector:
    """Component-wise mean."""
    count = len(vectors)
    return [sum(column) / count for column in zip(*vectors)]


def center(vec: Sequence[float], mean: Sequence[float]) -> Vector:
    """Subtract *mean* and renormalize."""
    return normalize([v - m for v, m in zip(vec, mean)])


def skewness(values: Sequence[float]) -> float:
    """Population skewness; 0.0 for constant input."""
    if len(values) < 2:
        return 0.0
    mu = statistics.fmean(values)
    sd = statistics.pstdev(values)
    if sd == 0.0:
        return 0.0
    return statistics.fmean(((v - mu) / sd) ** 3 for v in values)


def zscore_rows(matrix: Sequence[Sequence[float]]) -> List[List[float]]:
    """Per-row (per-candidate) z-score across columns (documents)."""
    out: List[List[float]] = []
    for row in matrix:
        mu = statistics.fmean(row)
        sd = statistics.pstdev(row)
        out.append([0.0 if sd == 0.0 else (v - mu) / sd for v in row])
    return out


class VectorBank:
    """Embeds each distinct text once and keeps its unit vector; times the calls."""

    def __init__(self, embedder: todo_embed.Embedder) -> None:
        self.embedder = embedder
        self.vectors: Dict[str, Vector] = {}
        self.seconds: Dict[str, float] = {}

    def embed_all(self, label: str, texts: Sequence[str]) -> None:
        """Embed every not-yet-seen text in *texts*, timing it under *label*."""
        start = time.monotonic()
        for text in texts:
            if text not in self.vectors:
                self.vectors[text] = normalize(self.embedder.embed(text))
        self.seconds[label] = self.seconds.get(label, 0.0) + time.monotonic() - start

    def __getitem__(self, text: str) -> Vector:
        return self.vectors[text]


class Space:
    """Document-side vectors under one vector correction (raw or centered)."""

    def __init__(
        self,
        bank: VectorBank,
        docs: Sequence[Doc],
        transform: Callable[[Vector], Vector],
        granularity: str,
    ) -> None:
        self.transform = transform
        self.doc_vectors = [transform(bank[d.text]) for d in docs]
        if granularity == "chunk":
            self.doc_units = [[transform(bank[c]) for c in d.chunks()] for d in docs]
        else:
            self.doc_units = [[v] for v in self.doc_vectors]

    def score_row(self, cand_vec: Vector) -> List[float]:
        """Score of one candidate against every document (max over its units)."""
        vec = self.transform(cand_vec)
        return [max(dot(vec, unit) for unit in units) for units in self.doc_units]


def _anisotropy(vectors: Sequence[Vector]) -> float:
    total = 0.0
    pairs = 0
    for i, a in enumerate(vectors):
        for b in vectors[i + 1 :]:
            total += dot(a, b)
            pairs += 1
    return total / pairs if pairs else 0.0


def _spread(matrix: Sequence[Sequence[float]]) -> Dict[str, float]:
    means = [statistics.fmean(row) for row in matrix]
    sds = [statistics.pstdev(row) for row in matrix]
    between = statistics.pstdev(means) if len(means) > 1 else 0.0
    within = statistics.fmean(sds)
    return {
        "range": max(means) - min(means),
        "between_sd": between,
        "within_sd": within,
        "signal_ratio": within / between if between else float("inf"),
    }


def _hubness(matrix: Sequence[Sequence[float]], candidates: Sequence[str], k: int) -> float:
    k = min(k, len(candidates))
    occurrence = [0] * len(candidates)
    for col in range(len(matrix[0]) if matrix else 0):
        ranked = sorted(range(len(candidates)), key=lambda r: (-matrix[r][col], candidates[r]))
        for r in ranked[:k]:
            occurrence[r] += 1
    return skewness(occurrence)


def _is_hit(domain: str, subject: str, candidate: str) -> bool:
    if domain == "L":
        return candidate in SUBJECTS[subject]
    return bool(set(todo_search.tokenize(candidate)) & GOLD_TERMS[subject])


def _precision(
    domain: str,
    matrix: Sequence[Sequence[float]],
    candidates: Sequence[str],
    subject_cols: Mapping[str, int],
    exclude: Mapping[str, Set[str]],
) -> Dict[str, object]:
    p1 = p3 = h3 = 0.0
    tops: Dict[str, List[Tuple[str, float]]] = {}
    for subject, col in subject_cols.items():
        banned = exclude.get(subject, set())
        ranked = sorted(
            (r for r in range(len(candidates)) if candidates[r] not in banned),
            key=lambda r: (-matrix[r][col], candidates[r]),
        )[:3]
        hits = [_is_hit(domain, subject, candidates[r]) for r in ranked]
        p1 += 1.0 if hits[:1] == [True] else 0.0
        p3 += sum(hits) / 3.0
        h3 += 1.0 if any(hits) else 0.0
        tops[subject] = [(candidates[r], round(matrix[r][col], 4)) for r in ranked]
    count = len(subject_cols) or 1
    return {"p_at_1": p1 / count, "p_at_3": p3 / count, "hit_at_3": h3 / count, "top3": tops}


def evaluate(
    embedder: todo_embed.Embedder,
    docs: Sequence[Doc],
    *,
    domains: Sequence[str] = DOMAINS,
    corrections: Sequence[str] = CORRECTIONS,
    granularity: str = "whole",
    windows: Callable[[str], List[str]] = _default_windows,
    hubness_k: int = HUBNESS_K,
) -> Dict[str, object]:
    """Embed once, evaluate every (domain x correction) cell; return a JSON-able dict."""
    wall_start = time.monotonic()
    doc_ids = [d.doc_id for d in docs]
    subject_cols: Dict[str, int] = {}
    for prefix in SUBJECTS:
        matches = [i for i, doc_id in enumerate(doc_ids) if doc_id.startswith(prefix)]
        if matches:
            subject_cols[prefix] = matches[0]

    domain_cands: Dict[str, List[str]] = {}
    exclude: Dict[str, Dict[str, Set[str]]] = {}
    for domain in domains:
        exclude[domain] = {}
        if domain == "W":
            domain_cands[domain] = word_domain(docs)
        elif domain == "P":
            cands, sources = phrase_domain(docs, windows)
            domain_cands[domain] = cands
            for prefix, col in subject_cols.items():
                own = doc_ids[col]
                exclude[domain][prefix] = {c for c, src in sources.items() if own in src}
        elif domain == "L":
            domain_cands[domain] = list(LABELS)
        else:
            raise ValueError(f"unknown domain {domain!r}; choose from {DOMAINS}")

    bank = VectorBank(embedder)
    bank.embed_all("documents", [d.text for d in docs])
    if granularity == "chunk":
        bank.embed_all("chunks", [c for d in docs for c in d.chunks()])
    series = list(LENGTH_IRRELEVANT + LENGTH_RELEVANT)
    bank.embed_all("candidates", series + [c for cs in domain_cands.values() for c in cs])

    mean = mean_vector([bank[d.text] for d in docs])
    spaces = {
        "raw": Space(bank, docs, lambda v: v, granularity),
        "centered": Space(bank, docs, lambda v: center(v, mean), granularity),
    }

    def matrix_for(cands: Sequence[str], correction: str) -> List[List[float]]:
        space = spaces["centered" if correction == "centered" else "raw"]
        rows = [space.score_row(bank[c]) for c in cands]
        return zscore_rows(rows) if correction == "z" else rows

    target_col = subject_cols.get(LENGTH_TARGET)
    space_results: Dict[str, Dict[str, object]] = {}
    domain_results: Dict[str, Dict[str, object]] = {d: {} for d in domain_cands}
    for correction in corrections:
        if correction not in CORRECTIONS:
            raise ValueError(f"unknown correction {correction!r}; choose from {CORRECTIONS}")
        cell: Dict[str, object] = {}
        if correction != "z":
            cell["anisotropy"] = _anisotropy(spaces[correction].doc_vectors)
        if target_col is not None:
            rows = matrix_for(series, correction)
            scores = {text: rows[i][target_col] for i, text in enumerate(series)}
            cell["length_bias"] = {
                "series": scores,
                "inversion_margin": scores[LENGTH_RELEVANT[1]] - scores[LENGTH_IRRELEVANT[-1]],
            }
        space_results[correction] = cell
        for domain, cands in domain_cands.items():
            matrix = matrix_for(cands, correction)
            result: Dict[str, object] = {
                "spread": _spread(matrix),
                "hubness_skew": _hubness(matrix, cands, hubness_k),
            }
            result.update(_precision(domain, matrix, cands, subject_cols, exclude[domain]))
            if domain == "L":
                result["labels"] = {
                    c: {"mean": statistics.fmean(row), "sd": statistics.pstdev(row)}
                    for c, row in zip(cands, matrix)
                }
            domain_results[domain][correction] = result

    return {
        "meta": {
            "fingerprint": embedder.fingerprint(),
            "dimension": embedder.dimension(),
            "documents": len(docs),
            "subjects_found": sorted(subject_cols),
            "domain_sizes": {d: len(c) for d, c in domain_cands.items()},
            "granularity": granularity,
            "hubness_k": hubness_k,
            "embed_seconds": bank.seconds,
            "wall_seconds": time.monotonic() - wall_start,
        },
        "space": space_results,
        "domains": domain_results,
    }


def spike_check(results: Mapping[str, object]) -> List[Tuple[str, float, float, float]]:
    """(name, spike, measured, measured - spike) for every recorded spike number."""
    rows: List[Tuple[str, float, float, float]] = []
    raw_space = results["space"].get("raw", {})  # type: ignore[union-attr]
    series = raw_space.get("length_bias", {}).get("series", {})
    for text, spike in SPIKE_LENGTH_SERIES.items():
        if text in series:
            rows.append((f"length {text!r}", spike, series[text], series[text] - spike))
    labels = results["domains"].get("L", {}).get("raw", {}).get("labels", {})  # type: ignore
    for label, (spike_mean, spike_sd) in SPIKE_LABEL_TABLE.items():
        if label in labels:
            got = labels[label]
            rows.append((f"mean {label!r}", spike_mean, got["mean"], got["mean"] - spike_mean))
            rows.append((f"sd   {label!r}", spike_sd, got["sd"], got["sd"] - spike_sd))
    return rows


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--embedder", default="apple", help="todo_embed selection key")
    parser.add_argument("--as-of", help="only todos with update_dt <= this ISO instant")
    parser.add_argument(
        "--include", action="append", default=[], help="Id prefix kept despite --as-of"
    )
    parser.add_argument("--exclude", action="append", default=[], help="Id prefix to drop")
    parser.add_argument("--domains", default=",".join(DOMAINS), help="comma list of W,P,L")
    parser.add_argument(
        "--corrections", default=",".join(CORRECTIONS), help="comma list of raw,centered,z"
    )
    parser.add_argument("--granularity", choices=("whole", "chunk"), default="whole")
    parser.add_argument("--out", help="write the full JSON result here (default: stdout)")
    parser.add_argument(
        "--check-spike",
        action="store_true",
        help="print todo:32ca7662 apple numbers vs measured (raw, whole) to stderr",
    )
    args = parser.parse_args(argv)

    docs = load_corpus(args.as_of, include=args.include, exclude=args.exclude)
    results = evaluate(
        todo_embed.get_embedder(args.embedder),
        docs,
        domains=[d for d in args.domains.split(",") if d],
        corrections=[c for c in args.corrections.split(",") if c],
        granularity=args.granularity,
    )
    results["meta"]["embedder_key"] = args.embedder  # type: ignore[index]
    results["meta"]["as_of"] = args.as_of  # type: ignore[index]
    results["meta"]["include"] = args.include  # type: ignore[index]
    results["meta"]["exclude"] = args.exclude  # type: ignore[index]
    text = json.dumps(results, indent=2, sort_keys=True)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(text + "\n")
    else:
        print(text)
    if args.check_spike:
        worst = 0.0
        for name, spike, got, delta in spike_check(results):
            worst = max(worst, abs(delta))
            print(
                f"{name:<110} spike {spike:+.4f}  got {got:+.4f}  delta {delta:+.4f}",
                file=sys.stderr,
            )
        print(f"max |delta| = {worst:.4f}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
