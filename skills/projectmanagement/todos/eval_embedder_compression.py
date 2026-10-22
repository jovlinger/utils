#!/usr/bin/env python3
"""Embedder compression eval harness (todo:1e3c7e0f; ports the todo:32ca7662 spike).

Measures how well an embedder's vector space resists cosine "compression" on the
todo corpus: every cosine landing in one narrow high band, and cosine ranking a
candidate's LENGTH above its topic.

Any ``todo_embed.Embedder`` can be evaluated. An embedder that also exposes
``embed_query(text)`` / ``embed_document(text)`` (asymmetric models with
per-role prefixes) is called through those; otherwise plain ``embed``. Candidates
(tags, labels, series) are QUERIES; todo texts and their chunks are DOCUMENTS.

Pure python (no numpy). Corpus is read through the ``todo.py`` CLI.

Usage::

    eval_embedder_compression.py --embedder apple --check-apple
    eval_embedder_compression.py --embedder apple --out results/apple.json

Metrics per (domain x correction): spread (between-candidate sd of per-candidate
mean cosine, mean within-candidate sd across docs, their ratio), anisotropy
(mean pairwise doc cosine), hubness (skew of k-occurrence, k=10), precision@1/@3
against gold. Corrections: raw, centered (subtract corpus mean, renormalize),
z (per-candidate z-score across docs). Metrics a correction cannot define are
None (anisotropy and spread under z).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import operator
import sqlite3
import struct
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import todo_embed
import todo_search

HERE = Path(__file__).resolve().parent
Vec = List[float]

K_OCC = 10
CORRECTIONS = ("raw", "centered", "z")
# Spike corpus: every todo created before the spike itself was written.
SPIKE_CREATED_BEFORE = "2026-08-05T13:24:08Z"
DOC_JOINER = " "

# -- gold (todo:32ca7662) ----------------------------------------------------

# (todo id prefix, spike label, curated labels that count as correct for the
# subject, keywords whose stemmed form makes a mined W/P candidate a hit)
SUBJECTS: List[Tuple[str, str, Tuple[str, ...], Tuple[str, ...]]] = [
    (
        "515fc9ea",
        "automated testing / sqlite storage",
        ("automated testing", "sqlite storage"),
        ("test", "sqlite", "storage"),
    ),
    ("cc756c32", "git worktrees", ("git worktrees",), ("worktree", "wt")),
    ("a31d8f24", "vector search ranking", ("vector search",), ("vector", "vec", "search", "rank")),
    (
        "a46c04b0",
        "audio (flac) file/directory naming from metadata",
        ("audio file metadata",),
        ("flac", "audio", "metadata"),
    ),
    (
        "21e3454c",
        "esp32 embedded http endpoints",
        ("embedded hardware",),
        ("esp32", "healthz", "embedded"),
    ),
    (
        "ef4ad78d",
        "semantic tagging with embeddings",
        ("semantic tagging",),
        ("tagging", "tag", "semantic", "embedding"),
    ),
]

# The 14 curated labels; the last four of the relevant-looking set are the
# spike's distractors.
LABELS: List[Tuple[str, bool]] = [
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
]

LENGTH_TARGET = "a46c04b0"
IRRELEVANT_WORDS = (
    "git branch checkout worktree inventory teardown stale "
    "commit push merge rebase origin master"
).split()
RELEVANT_CANDIDATES = ("flac", "audio metadata", "flac audio metadata directory naming")

# Spike reference (apple, todo:32ca7662 Body, EVIDENCE 1 and 2).
REF_LENGTH = {
    "git": 0.476,
    "git branch checkout worktree": 0.832,
    "git branch checkout worktree inventory teardown stale": 0.875,
    " ".join(IRRELEVANT_WORDS): 0.895,
    "flac": 0.645,
    "audio metadata": 0.698,
    "flac audio metadata directory naming": 0.916,
}
REF_LABELS: Dict[str, Tuple[float, float]] = {
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
REPRO_TOLERANCE = 0.01

# -- vector math -------------------------------------------------------------


def dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(map(operator.mul, a, b))


def normalize(v: Sequence[float]) -> Vec:
    n = math.sqrt(dot(v, v))
    return [x / n for x in v] if n else list(v)


def mean_vec(vs: Sequence[Sequence[float]]) -> Vec:
    n = len(vs)
    return [sum(col) / n for col in zip(*vs)]


def center(v: Sequence[float], mu: Sequence[float]) -> Vec:
    return normalize([x - m for x, m in zip(v, mu)])


def mean_sd(xs: Sequence[float]) -> Tuple[float, float]:
    n = len(xs)
    m = sum(xs) / n
    return m, math.sqrt(sum((x - m) ** 2 for x in xs) / n) if n else 0.0


def skewness(xs: Sequence[float]) -> float:
    m, sd = mean_sd(xs)
    if sd == 0.0:
        return 0.0
    return sum(((x - m) / sd) ** 3 for x in xs) / len(xs)


def zscores(row: Sequence[float]) -> List[float]:
    m, sd = mean_sd(row)
    if sd == 0.0:
        return [0.0] * len(row)
    return [(x - m) / sd for x in row]


# -- embedding with cache ----------------------------------------------------


class Embedding:
    """Role-aware, optionally sqlite-cached view of one Embedder."""

    def __init__(self, embedder: todo_embed.Embedder, cache_path: Optional[str] = None) -> None:
        self.embedder = embedder
        self.fingerprint = embedder.fingerprint()
        self._db: Optional[sqlite3.Connection] = None
        self.embed_seconds = 0.0
        self.embed_calls = 0
        if cache_path:
            self._db = sqlite3.connect(cache_path)
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS v (fp TEXT, role TEXT, h TEXT, vec BLOB,"
                " PRIMARY KEY (fp, role, h))"
            )

    def _raw(self, text: str, role: str) -> Vec:
        fn: Callable[[str], Vec] = (
            getattr(self.embedder, "embed_" + role, None) or self.embedder.embed
        )
        t0 = time.time()
        vec = [float(x) for x in fn(text)]
        self.embed_seconds += time.time() - t0
        self.embed_calls += 1
        return vec

    def get(self, text: str, role: str) -> Vec:
        if self._db is None:
            return self._raw(text, role)
        h = hashlib.sha1(text.encode("utf-8")).hexdigest()
        row = self._db.execute(
            "SELECT vec FROM v WHERE fp=? AND role=? AND h=?", (self.fingerprint, role, h)
        ).fetchone()
        if row:
            blob = row[0]
            return list(struct.unpack(f"<{len(blob) // 8}d", blob))
        vec = self._raw(text, role)
        self._db.execute(
            "INSERT OR REPLACE INTO v VALUES (?,?,?,?)",
            (self.fingerprint, role, h, struct.pack(f"<{len(vec)}d", *vec)),
        )
        return vec

    def commit(self) -> None:
        if self._db is not None:
            self._db.commit()

    def many(self, texts: Iterable[str], role: str) -> Dict[str, Vec]:
        out: Dict[str, Vec] = {}
        for text in texts:
            if text not in out:
                out[text] = self.get(text, role)
        self.commit()
        return out


# -- corpus ------------------------------------------------------------------


class Doc:
    def __init__(self, ident: str, created: str, state: str, summary: str, body: str) -> None:
        self.ident = ident
        self.created = created
        self.state = state
        self.summary = summary
        self.body = body

    @property
    def text(self) -> str:
        return DOC_JOINER.join(p for p in (self.summary, self.body) if p)


def load_corpus(
    todo_py: Path = HERE / "todo.py", created_before: Optional[str] = None
) -> List[Doc]:
    """Every todo (all states) via ``todo.py ls`` / ``todo.py read``."""
    listing = subprocess.run(
        [str(todo_py), "ls", "-s", "-t"], capture_output=True, text=True, check=True, cwd=HERE
    ).stdout
    docs: List[Doc] = []
    for line in listing.splitlines():
        parts = line.split(None, 3)
        if len(parts) < 3:
            continue
        state, created, ident = parts[0], parts[1], parts[2]
        if created_before and created >= created_before:
            continue
        raw = subprocess.run(
            [str(todo_py), "read", ident], capture_output=True, text=True, check=True, cwd=HERE
        ).stdout
        rec = json.loads(raw)
        docs.append(
            Doc(
                ident,
                created,
                state,
                (rec.get("Summary") or {}).get("raw") or "",
                (rec.get("Body") or {}).get("raw") or "",
            )
        )
    return docs


# -- candidate domains and chunking -----------------------------------------


def nphrase_windows(text: str, max_n: int = 3) -> List[str]:
    """The shipped n-phrase chunker (todo.py ``_nphrase_windows``)."""
    import todo  # lazy: todo.py is large

    return todo._nphrase_windows(text, max_n)  # pylint: disable=protected-access


def candidates_w(texts: Sequence[str], min_df: int = 2) -> List[str]:
    """Stemmed word 1..3-grams, corpus-wide, in at least ``min_df`` documents."""
    df: Counter = Counter()
    for text in texts:
        toks = todo_search.tokenize(text)
        grams = {" ".join(toks[i : i + n]) for n in (1, 2, 3) for i in range(len(toks) - n + 1)}
        df.update(grams)
    return sorted(g for g, c in df.items() if c >= min_df)


def candidates_p(texts: Sequence[str]) -> List[str]:
    """Deduped lowercased 1..3-phrase windows, first-appearance order."""
    seen: Dict[str, None] = {}
    for text in texts:
        for window in nphrase_windows(text):
            c = window.strip().lower()
            if c:
                seen.setdefault(c, None)
    return list(seen)


# -- scoring -----------------------------------------------------------------


def score_matrix(cands: Sequence[Vec], docs: Sequence[Vec]) -> List[List[float]]:
    """S[c][d] = cosine (inputs are unit vectors, so a dot product)."""
    return [[dot(c, d) for d in docs] for c in cands]


def apply_correction(
    correction: str, cand_vecs: Sequence[Vec], doc_vecs: Sequence[Vec]
) -> Tuple[List[List[float]], Optional[List[Vec]]]:
    """Return (score matrix in the corrected space, doc vectors in that space)."""
    if correction == "raw":
        return score_matrix(cand_vecs, doc_vecs), list(doc_vecs)
    if correction == "centered":
        mu = mean_vec(doc_vecs)
        cd = [center(d, mu) for d in doc_vecs]
        cc = [center(c, mu) for c in cand_vecs]
        return score_matrix(cc, cd), cd
    if correction == "z":
        raw = score_matrix(cand_vecs, doc_vecs)
        return [zscores(row) for row in raw], None
    raise ValueError(correction)


def anisotropy(doc_vecs: Sequence[Vec]) -> float:
    n = len(doc_vecs)
    total = 0.0
    for i in range(n):
        for j in range(i + 1, n):
            total += dot(doc_vecs[i], doc_vecs[j])
    return total / (n * (n - 1) / 2)


def spread(S: Sequence[Sequence[float]]) -> Dict[str, float]:
    stats = [mean_sd(row) for row in S]
    means = [m for m, _ in stats]
    sds = [s for _, s in stats]
    between_sd = mean_sd(means)[1]
    within = sum(sds) / len(sds)
    return {
        "between_sd": between_sd,
        "between_range": max(means) - min(means),
        "within_sd": within,
        "ratio": between_sd / within if within else float("inf"),
    }


def hubness(S: Sequence[Sequence[float]], k: int = K_OCC) -> float:
    """Skew of k-occurrence: how often each candidate is a doc's top-k."""
    n_cand = len(S)
    n_doc = len(S[0])
    counts = [0] * n_cand
    for d in range(n_doc):
        ranked = sorted(range(n_cand), key=lambda c, d=d: (-S[c][d], c))
        col = ranked[:k]
        for c in col:
            counts[c] += 1
    return skewness(counts)


def is_hit(cand: str, keywords: Sequence[str]) -> bool:
    stems = set(todo_search.tokenize(cand))
    return any(todo_search.stem(k) in stems for k in keywords)


def precision(
    S: Sequence[Sequence[float]],
    cands: Sequence[str],
    subject_cols: Sequence[int],
    hit: Callable[[int, str], bool],
    excluded: Callable[[int, str], bool] = lambda s, c: False,
) -> Dict[str, float]:
    """precision@1/@3 over the subjects; ties broken on candidate text ascending."""
    p1 = p3 = 0
    for si, col in enumerate(subject_cols):
        order = sorted(
            (c for c in range(len(cands)) if not excluded(si, cands[c])),
            key=lambda c, col=col: (-S[c][col], cands[c]),
        )[:3]
        if order and hit(si, cands[order[0]]):
            p1 += 1
        if any(hit(si, cands[c]) for c in order):
            p3 += 1
    n = len(subject_cols)
    return {"p@1": p1 / n, "p@3": p3 / n}


# -- the experiment ----------------------------------------------------------


def length_bias(
    emb: Embedding, target_vec: Vec, doc_vecs: Sequence[Vec], correction: str
) -> Dict[str, Any]:
    """Cosine of each candidate to the fixed target, in the given correction."""
    series = [" ".join(IRRELEVANT_WORDS[: i + 1]) for i in range(len(IRRELEVANT_WORDS))]
    texts = series + list(RELEVANT_CANDIDATES)
    qv = emb.many(texts, "query")
    out: Dict[str, float] = {}
    if correction == "raw":
        for t in texts:
            out[t] = dot(qv[t], target_vec)
    elif correction == "centered":
        mu = mean_vec(doc_vecs)
        tc = center(target_vec, mu)
        for t in texts:
            out[t] = dot(center(qv[t], mu), tc)
    else:
        for t in texts:
            row = [dot(qv[t], d) for d in doc_vecs]
            m, sd = mean_sd(row)
            out[t] = (dot(qv[t], target_vec) - m) / sd if sd else 0.0
    irrelevant13 = out[" ".join(IRRELEVANT_WORDS)]
    relevant2 = out["audio metadata"]
    return {
        "series": out,
        "inversion_ok": relevant2 > irrelevant13,
        "relevant2_minus_irrelevant13": relevant2 - irrelevant13,
    }


def label_table(emb: Embedding, doc_vecs: Sequence[Vec], correction: str) -> List[Dict[str, Any]]:
    qv = emb.many([name for name, _ in LABELS], "query")
    S, _ = apply_correction(correction, [qv[n] for n, _ in LABELS], doc_vecs)
    rows = []
    for (name, distractor), row in zip(LABELS, S):
        m, sd = mean_sd(row)
        rows.append({"label": name, "distractor": distractor, "mean": m, "sd": sd})
    return rows


def subject_columns(docs: Sequence[Doc]) -> List[int]:
    idx = {d.ident[:8]: i for i, d in enumerate(docs)}
    return [idx[s[0]] for s in SUBJECTS]


def evaluate(
    embedder: todo_embed.Embedder,
    docs: Sequence[Doc],
    *,
    cache_path: Optional[str] = None,
    domains: Sequence[str] = ("D", "W", "P"),
    chunk_labels: bool = True,
    log: Callable[[str], None] = lambda _m: None,
) -> Dict[str, Any]:
    emb = Embedding(embedder, cache_path)
    t0 = time.time()
    texts = [d.text for d in docs]
    log(f"embedding {len(texts)} documents")
    dv_map = emb.many(texts, "document")
    doc_vecs = [normalize(dv_map[t]) for t in texts]
    cols = subject_columns(docs)
    target_vec = doc_vecs[[d.ident[:8] for d in docs].index(LENGTH_TARGET)]

    result: Dict[str, Any] = {
        "fingerprint": emb.fingerprint,
        "dim": embedder.dimension(),
        "docs": len(docs),
        "anisotropy": {},
        "length_bias": {},
        "domains": {},
    }
    for corr in CORRECTIONS:
        result["length_bias"][corr] = length_bias(emb, target_vec, doc_vecs, corr)
        if corr != "z":
            result["anisotropy"][corr] = anisotropy(apply_correction(corr, [], doc_vecs)[1] or [])
        else:
            result["anisotropy"][corr] = None

    subj_windows = [set(w.strip().lower() for w in nphrase_windows(docs[c].text)) for c in cols]

    def hit_and_excluded(
        name: str,
    ) -> Tuple[Callable[[int, str], bool], Callable[[int, str], bool]]:
        if name == "D":
            return (lambda si, cand: cand in SUBJECTS[si][2]), (lambda si, cand: False)
        hit = lambda si, cand: is_hit(cand, SUBJECTS[si][3])
        if name == "P":  # a phrase lifted from the subject itself is a tautological match
            return hit, (lambda si, cand: cand in subj_windows[si])
        return hit, (lambda si, cand: False)

    def run_domain(name: str, cands: List[str]) -> None:
        log(f"domain {name}: embedding {len(cands)} candidates")
        qv_map = emb.many(cands, "query")
        cand_vecs = [normalize(qv_map[c]) for c in cands]
        by_corr: Dict[str, Any] = {}
        for corr in CORRECTIONS:
            S, _ = apply_correction(corr, cand_vecs, doc_vecs)
            hit, excl = hit_and_excluded(name)
            entry: Dict[str, Any] = {"n_candidates": len(cands)}
            entry["spread"] = spread(S) if corr != "z" else None
            entry["hubness"] = hubness(S) if len(cands) > K_OCC else None
            entry.update(precision(S, cands, cols, hit, excl))
            by_corr[corr] = entry
        result["domains"][name] = by_corr

    if "D" in domains:
        run_domain("D", [n for n, _ in LABELS])
        if chunk_labels:
            result["domains"]["D"]["chunk"] = chunk_label_precision(emb, docs, cols, doc_vecs)
    if "W" in domains:
        run_domain("W", candidates_w(texts))
    if "P" in domains:
        run_domain("P", candidates_p(texts))

    result["label_table_raw"] = label_table(emb, doc_vecs, "raw")
    result["embed_calls"] = emb.embed_calls
    result["embed_seconds"] = emb.embed_seconds
    result["wall_seconds"] = time.time() - t0
    return result


def chunk_label_precision(
    emb: Embedding, docs: Sequence[Doc], cols: Sequence[int], doc_vecs: Sequence[Vec]
) -> Dict[str, Any]:
    """Curated labels scored by MAX cosine over a subject's n-phrase chunks."""
    names = [n for n, _ in LABELS]
    lv = [normalize(v) for v in (emb.many(names, "query")[n] for n in names)]
    out: Dict[str, Any] = {}
    for corr in ("raw", "centered"):
        mu = mean_vec(doc_vecs)
        p1 = p3 = 0
        for si, col in enumerate(cols):
            chunks = sorted(set(nphrase_windows(docs[col].text)))
            cm = emb.many(chunks, "document")
            cv = [normalize(cm[c]) for c in chunks]
            lq = lv
            if corr == "centered":
                cv = [center(c, mu) for c in cv]
                lq = [center(v, mu) for v in lv]
            scores = [max(dot(l, c) for c in cv) for l in lq]
            order = sorted(range(len(names)), key=lambda i, sc=scores: (-sc[i], names[i]))[:3]
            gold = SUBJECTS[si][2]
            p1 += names[order[0]] in gold
            p3 += any(names[i] in gold for i in order)
        out[corr] = {"p@1": p1 / len(cols), "p@3": p3 / len(cols)}
    return out


# -- reproduction check ------------------------------------------------------


def check_apple(result: Dict[str, Any], tol: float = REPRO_TOLERANCE) -> Tuple[bool, List[str]]:
    """Compare raw length-bias series and label mean/sd to the spike's numbers."""
    lines: List[str] = []
    ok = True
    series = result["length_bias"]["raw"]["series"]
    for text, ref in REF_LENGTH.items():
        got = series[text]
        good = abs(got - ref) <= tol
        ok &= good
        lines.append(
            f"{'ok  ' if good else 'FAIL'} length {got:+.4f} ref {ref:+.3f} d={got - ref:+.4f}  {text[:48]}"
        )
    for row in result["label_table_raw"]:
        rm, rs = REF_LABELS[row["label"]]
        dm, ds = row["mean"] - rm, row["sd"] - rs
        good = abs(dm) <= tol and abs(ds) <= tol
        ok &= good
        lines.append(
            f"{'ok  ' if good else 'FAIL'} label  mean {row['mean']:+.4f} (ref {rm:+.4f} d={dm:+.4f})"
            f" sd {row['sd']:.4f} (ref {rs:.4f} d={ds:+.4f})  {row['label']}"
        )
    return ok, lines


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--embedder", default="apple", help="todo_embed selection key")
    ap.add_argument("--cache", help="sqlite vector cache path (optional)")
    ap.add_argument("--out", help="write full results JSON here")
    ap.add_argument("--domains", default="D,W,P")
    ap.add_argument("--created-before", help="corpus cut (ISO time); default: all todos")
    ap.add_argument("--spike-corpus", action="store_true", help=f"cut at {SPIKE_CREATED_BEFORE}")
    ap.add_argument("--check-apple", action="store_true", help="compare to the spike numbers")
    args = ap.parse_args(argv)

    cut = SPIKE_CREATED_BEFORE if args.spike_corpus else args.created_before
    docs = load_corpus(created_before=cut)
    emb = todo_embed.get_embedder(args.embedder)
    result = evaluate(
        emb,
        docs,
        cache_path=args.cache,
        domains=args.domains.split(","),
        log=lambda m: print(m, file=sys.stderr),
    )
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2, sort_keys=True), encoding="ascii")
    print(
        json.dumps(
            {k: v for k, v in result.items() if k != "label_table_raw"}, indent=1, sort_keys=True
        )
    )
    if args.check_apple:
        ok, lines = check_apple(result)
        print("\n".join(lines))
        print("REPRODUCTION", "OK" if ok else "FAILED", f"(tolerance +-{REPRO_TOLERANCE})")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
