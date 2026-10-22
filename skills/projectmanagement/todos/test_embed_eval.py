#!/usr/bin/env python3
"""Unit tests for the embedder compression-eval harness (embed_eval.py).

Every embedder here is an in-process fake; nothing touches the network, the
sidecar, a store, or the filesystem.
"""

from __future__ import annotations

import math
import unittest
from typing import Dict, List

import embed_eval
import todo_embed


class RoleEmbedder(todo_embed.Embedder):
    """Fake that distinguishes query and document roles and counts calls."""

    def __init__(self) -> None:
        self.calls: List[str] = []

    def fingerprint(self) -> str:
        return "role-fake"

    def dimension(self) -> int:
        return 2

    def embed(self, text: str) -> List[float]:
        self.calls.append("embed")
        return [1.0, 0.0]

    def embed_query(self, _text: str) -> List[float]:
        self.calls.append("query")
        return [0.0, 1.0]

    def embed_document(self, _text: str) -> List[float]:
        self.calls.append("document")
        return [1.0, 0.0]


class BagEmbedder(todo_embed.Embedder):
    """Finite deterministic fake: letter-count vector plus a constant offset."""

    def fingerprint(self) -> str:
        return "bag-fake"

    def dimension(self) -> int:
        return 27

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * 27
        for ch in text.lower():
            vec[ord(ch) - 97 if "a" <= ch <= "z" else 26] += 1.0
        vec[26] += 1.0
        return vec


class StatsTest(unittest.TestCase):
    def test_skewness_of_symmetric_values_is_zero(self) -> None:
        self.assertAlmostEqual(embed_eval.skewness([1, 2, 3, 4, 5]), 0.0)

    def test_skewness_of_right_tailed_values_is_positive(self) -> None:
        self.assertGreater(embed_eval.skewness([0, 0, 0, 0, 0, 0, 0, 10]), 1.0)

    def test_skewness_of_constant_values_is_zero(self) -> None:
        self.assertEqual(embed_eval.skewness([3, 3, 3, 3]), 0.0)

    def test_zscores_have_zero_mean_and_unit_sd(self) -> None:
        z = embed_eval.zscores([1.0, 2.0, 3.0, 10.0])
        self.assertAlmostEqual(sum(z), 0.0)
        self.assertAlmostEqual(sum(x * x for x in z) / len(z), 1.0)

    def test_zscores_of_constant_values_are_zero(self) -> None:
        self.assertEqual(embed_eval.zscores([2.0, 2.0]), [0.0, 0.0])


class CorrectionTest(unittest.TestCase):
    def setUp(self) -> None:
        # Docs share a large common offset on axis 0; they differ on axis 1.
        self.docs = [embed_eval.unit(v) for v in ([10.0, 1.0], [10.0, -1.0], [10.0, 0.5])]
        self.cands = [embed_eval.unit([1.0, 1.0]), embed_eval.unit([1.0, -1.0])]

    def test_raw_scores_are_plain_cosines(self) -> None:
        s = embed_eval.correct_scores(self.cands, self.docs, "raw")
        self.assertAlmostEqual(s[0][0], embed_eval.dot(self.cands[0], self.docs[0]))

    def test_z_scores_each_candidate_row_to_zero_mean(self) -> None:
        s = embed_eval.correct_scores(self.cands, self.docs, "z")
        for row in s:
            self.assertAlmostEqual(sum(row), 0.0)

    def test_centering_removes_shared_offset_from_anisotropy(self) -> None:
        raw = embed_eval.anisotropy(self.docs, [], "raw")
        centered = embed_eval.anisotropy(self.docs, [], "centered")
        self.assertGreater(raw, 0.95)
        self.assertLess(centered, 0.5)

    def test_unknown_correction_raises(self) -> None:
        with self.assertRaises(ValueError):
            embed_eval.correct_scores(self.cands, self.docs, "bogus")


class HubnessTest(unittest.TestCase):
    def test_a_candidate_in_every_top_k_list_gives_positive_skew(self) -> None:
        # 12 candidates, 5 docs; candidate 0 is rank 1 for every doc and the rest
        # are spread so only a few other candidates ever enter a top-1 list.
        scores = [[1.0] * 5] + [[0.1 * i] * 5 for i in range(1, 12)]
        self.assertGreater(embed_eval.hubness(scores, k=1), 1.0)

    def test_evenly_shared_top_slots_give_zero_skew(self) -> None:
        # candidate i is the unique winner of doc i.
        scores = [[1.0 if i == j else 0.0 for j in range(4)] for i in range(4)]
        self.assertEqual(embed_eval.hubness(scores, k=1), 0.0)


class DomainTest(unittest.TestCase):
    def test_word_candidates_keep_only_repeated_stemmed_ngrams(self) -> None:
        texts = ["merging branches daily", "branch merges often"]
        got = embed_eval.word_candidates(texts, min_freq=2)
        self.assertIn("branch", got)
        self.assertIn("merg", got)
        self.assertNotIn("daily", got)

    def test_phrase_candidates_are_lowercase_and_deduped(self) -> None:
        got = embed_eval.phrase_candidates(["Alpha beta. Gamma.", "alpha beta. gamma."])
        self.assertEqual(len(got), len(set(got)))
        self.assertIn("alpha beta", got)
        self.assertTrue(all(c == c.lower() for c in got))


class PrecisionTest(unittest.TestCase):
    def test_curated_precision_counts_gold_label_in_top_k(self) -> None:
        labels = ["automated testing", "git worktrees", "other"]
        index = {sid: i for i, sid in enumerate(embed_eval.GOLD_SUBJECTS)}
        n = len(index)
        # Every subject ranks "git worktrees" first, "automated testing" second.
        scores = [[0.5] * n, [0.9] * n, [0.1] * n]
        got = embed_eval.precision_curated(scores, labels, index)
        self.assertAlmostEqual(got["p_at_1"], 1 / n)  # only the worktrees subject
        self.assertAlmostEqual(got["p_at_3"], 2 / n)  # plus the testing subject

    def test_mined_precision_skips_candidates_found_in_the_subject(self) -> None:
        sids = list(embed_eval.GOLD_SUBJECTS)
        index = {sid: i for i, sid in enumerate(sids)}
        texts = {sid: "unrelated text" for sid in sids}
        texts["cc756c32"] = "a note about worktrees"
        candidates = ["worktrees", "worktree inventory"]
        # Both candidates score identically for every doc; the first occurs in
        # the subject's own text, so only the second may hit.
        scores = [[1.0] * len(sids), [0.5] * len(sids)]
        got = embed_eval.precision_mined(scores, candidates, index, texts)
        self.assertAlmostEqual(got["p_at_1"], 1 / len(sids))


class SpaceTest(unittest.TestCase):
    def test_roles_route_to_query_and_document_methods(self) -> None:
        emb = RoleEmbedder()
        space = embed_eval.Space(emb)
        self.assertEqual(space.query("x"), [0.0, 1.0])
        self.assertEqual(space.document("x"), [1.0, 0.0])
        self.assertEqual(emb.calls, ["query", "document"])

    def test_vectors_are_cached_per_role_and_text(self) -> None:
        emb = RoleEmbedder()
        space = embed_eval.Space(emb)
        space.query("x")
        space.query("x")
        self.assertEqual(emb.calls, ["query"])
        self.assertEqual(space.embed_calls, 1)

    def test_plain_embedder_serves_both_roles(self) -> None:
        space = embed_eval.Space(BagEmbedder())
        self.assertEqual(space.query("x"), space.document("x"))


class EvaluateTest(unittest.TestCase):
    def _rows(self) -> List[Dict[str, str]]:
        rows = []
        for sid, (gold, _) in embed_eval.GOLD_SUBJECTS.items():
            rows.append(
                {"id": sid, "c": "2026-07-01", "s": gold, "b": f"body about {gold}. more text"}
            )
        rows.append(
            {
                "id": "ffffffff",
                "c": "2026-07-02",
                "s": "filler",
                "b": "filler text. filler text again",
            }
        )
        return rows

    def test_full_run_with_mock_embedder_fills_every_cell(self) -> None:
        report = embed_eval.evaluate(BagEmbedder(), self._rows())
        self.assertEqual(len(report["cells"]), 9)
        self.assertEqual({c["domain"] for c in report["cells"]}, {"W", "P", "D"})
        self.assertEqual({c["correction"] for c in report["cells"]}, set(embed_eval.CORRECTIONS))
        self.assertEqual(report["docs"], 7)
        for cell in report["cells"]:
            self.assertTrue(math.isfinite(cell["anisotropy"]))
            self.assertTrue(0.0 <= cell["p_at_1"] <= cell["p_at_3"] <= 1.0)
        self.assertEqual(set(report["length_bias"]), set(embed_eval.CORRECTIONS))

    def test_missing_gold_subject_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            embed_eval.evaluate(BagEmbedder(), [{"id": "ffffffff", "c": "x", "s": "a", "b": "b"}])

    def test_length_series_reports_inversion_when_relevant_scores_higher(self) -> None:
        space = embed_eval.Space(BagEmbedder())
        target = space.query("audio metadata")  # identical to the 2-word relevant candidate
        docs = [space.document(t) for t in ("a", "b", "c")]
        got = embed_eval.length_series(space, target, docs, "raw")
        self.assertAlmostEqual(got["series"]["audio metadata"], 1.0)
        self.assertTrue(got["inverted"])


class ReproductionTest(unittest.TestCase):
    def test_rows_flag_values_outside_the_tolerance(self) -> None:
        label = "git worktrees"
        want_mean, want_sd = embed_eval.RECORDED_LABELS[label]
        report = {
            "raw_label_table": [{"label": label, "mean": want_mean + 0.005, "sd": want_sd + 0.02}],
            "length_bias": {},
        }
        rows = embed_eval.reproduction_rows(report)
        flags = {r["what"]: r["within_tolerance"] for r in rows}
        self.assertTrue(flags[f"label mean: {label}"])
        self.assertFalse(flags[f"label sd: {label}"])


if __name__ == "__main__":
    unittest.main()
