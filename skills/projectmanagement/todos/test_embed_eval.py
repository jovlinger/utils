#!/usr/bin/env python3
"""Unit tests for the embedder evaluation harness metrics.

Hermetic: no network, no sidecar, no store. Vectors come from a small in-test
embedder whose outputs are chosen so the expected metric values are exact.
"""

from __future__ import annotations

import math
import unittest
from typing import Dict, List

import embed_eval as ee
from todo_embed import Embedder


class TableEmbedder(Embedder):
    """Returns fixed vectors for known texts; unknown texts get a unit x-axis vector."""

    def __init__(self, table: Dict[str, List[float]]) -> None:
        self._table = table
        self._dim = len(next(iter(table.values())))

    def fingerprint(self) -> str:
        return "test-table"

    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        return list(self._table.get(text, [1.0] + [0.0] * (self._dim - 1)))


class VectorHelperTests(unittest.TestCase):
    def test_unit_normalizes(self) -> None:
        self.assertAlmostEqual(sum(x * x for x in ee._unit([3.0, 4.0])), 1.0)

    def test_unit_keeps_zero_vector(self) -> None:
        self.assertEqual(ee._unit([0.0, 0.0]), [0.0, 0.0])

    def test_dot_of_unit_vectors_is_cosine(self) -> None:
        self.assertAlmostEqual(ee.dot(ee._unit([1.0, 0.0]), ee._unit([1.0, 1.0])), 1 / math.sqrt(2))

    def test_vectors_cache_embeds_once(self) -> None:
        calls: List[str] = []

        class Counting(TableEmbedder):
            def embed(self, text: str) -> List[float]:
                calls.append(text)
                return super().embed(text)

        vec = ee.Vectors(Counting({"a": [1.0, 0.0]}))
        self.assertIs(vec("a"), vec("a"))
        self.assertEqual(calls, ["a"])
        self.assertEqual(vec.embeds, 1)


class ScorerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.docs = [ee._unit(v) for v in ([1.0, 0.0], [0.0, 1.0], [1.0, 1.0])]

    def test_raw_is_plain_cosine(self) -> None:
        scorer = ee.Scorer("raw", self.docs)
        cand = scorer.pair(ee._unit([1.0, 0.0]))
        subj = [scorer.pair(ee._unit([1.0, 1.0]))]
        self.assertAlmostEqual(scorer.score(cand, subj), 1 / math.sqrt(2))

    def test_subject_chunks_score_by_max(self) -> None:
        scorer = ee.Scorer("raw", self.docs)
        cand = scorer.pair([1.0, 0.0])
        subj = [scorer.pair([0.0, 1.0]), scorer.pair([1.0, 0.0])]
        self.assertAlmostEqual(scorer.score(cand, subj), 1.0)

    def test_centering_removes_corpus_mean(self) -> None:
        scorer = ee.Scorer("centered", self.docs)
        mean = ee.mean_vector(self.docs)
        raw, prep = scorer.pair(self.docs[0])
        expected = ee._unit([x - m for x, m in zip(self.docs[0], mean)])
        for got, want in zip(prep, expected):
            self.assertAlmostEqual(got, want)
        self.assertIs(raw, self.docs[0])

    def test_z_is_per_candidate_over_docs(self) -> None:
        scorer = ee.Scorer("z", self.docs)
        cand = self.docs[2]
        sims = [ee.dot(cand, d) for d in self.docs]
        mu = sum(sims) / len(sims)
        sd = math.sqrt(sum((s - mu) ** 2 for s in sims) / len(sims))
        subj = [scorer.pair(self.docs[0])]
        best = ee.dot(cand, self.docs[0])
        self.assertAlmostEqual(scorer.score(scorer.pair(cand), subj), (best - mu) / sd)

    def test_unknown_correction_rejected(self) -> None:
        with self.assertRaises(ValueError):
            ee.Scorer("bogus", self.docs)


class MetricTests(unittest.TestCase):
    def test_spread_ratio_is_range_over_mean_sd(self) -> None:
        table = [
            {"mean": 0.8, "sd": 0.02},
            {"mean": 0.6, "sd": 0.04},
        ]
        self.assertAlmostEqual(ee.spread_ratio(table), round(0.2 / 0.03, 3))

    def test_anisotropy_mean_pairwise_cosine(self) -> None:
        docs = [[1.0, 0.0], [0.0, 1.0], [1.0, 0.0]]
        # pairs: (0,1)=0, (0,2)=1, (1,2)=0
        self.assertAlmostEqual(ee.anisotropy(docs), round(1 / 3, 4))

    def test_hubness_skew_zero_for_symmetric_occurrences(self) -> None:
        # k=1 nearest neighbours: doc0->doc1, doc1->doc0, doc2->doc0 (tie broken by
        # index). k-occurrence counts are [2, 1, 0], symmetric about their mean.
        docs = [[1.0, 0.0], [1.0, 0.0], [0.0, 1.0]]
        self.assertEqual(ee.hubness_skew(docs, k=1), 0.0)

    def test_hit_is_stemmed_token_containment(self) -> None:
        self.assertTrue(ee._is_hit("vector search ranking", ("vector search",)))
        self.assertTrue(ee._is_hit("sqlite storage suite", ("sqlite storage",)))
        self.assertFalse(ee._is_hit("git", ("git worktrees",)))

    def test_word_ngram_candidates_need_two_documents(self) -> None:
        cands = ee.word_ngram_candidates(["alpha beta", "alpha gamma", "delta"])
        self.assertIn("alpha", cands)
        self.assertNotIn("gamma", cands)
        self.assertNotIn("delta", cands)


class LengthSeriesTests(unittest.TestCase):
    def test_series_covers_spike_candidates_with_all_corrections(self) -> None:
        table = {ee.DEFAULT_LENGTH_TARGET: [1.0, 0.0, 0.0]}
        for text in ee.IRRELEVANT + ee.RELEVANT:
            table[text] = [1.0, 0.1, 0.0]
        embedder = TableEmbedder(table)
        vec = ee.Vectors(embedder)
        docs = [ee._unit([1.0, 0.0, 0.0]), ee._unit([0.0, 1.0, 0.0]), ee._unit([0.0, 0.0, 1.0])]
        rows = ee.length_series(vec, ee.DEFAULT_LENGTH_TARGET, docs)
        self.assertEqual(len(rows), len(ee.IRRELEVANT) + len(ee.RELEVANT))
        self.assertEqual(
            [r["words"] for r in rows[: len(ee.IRRELEVANT)]],
            [len(t.split()) for t in ee.IRRELEVANT],
        )
        for row in rows:
            for corr in ee.CORRECTIONS:
                self.assertIn(corr, row)


if __name__ == "__main__":
    unittest.main()
