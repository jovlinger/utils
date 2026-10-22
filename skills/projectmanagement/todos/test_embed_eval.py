#!/usr/bin/env python3
"""Unit tests for the embedder compression eval harness (embed_eval.py)."""

from __future__ import annotations

import math
import unittest
import unittest.mock

import embed_eval
import fake_nlce


def _doc(doc_id: str, summary: str, body: str = "") -> embed_eval.Doc:
    return embed_eval.Doc(doc_id, summary, body)


def _corpus() -> list:
    return [
        _doc(
            "a46c04b0" + "0" * 56, "flac audio metadata", "Rename flac directories. Use audio tags."
        ),
        _doc("cc756c32" + "0" * 56, "git worktrees", "List stale git worktrees. Remove them."),
        _doc("a31d8f24" + "0" * 56, "vector search ranking", "Rank vector search hits."),
        _doc("ffff0000" + "0" * 56, "billing invoices", "Send invoices. Use audio tags."),
    ]


class DomainTest(unittest.TestCase):
    """Candidate domains W and P."""

    def test_word_domain_is_stemmed_and_frequency_filtered(self) -> None:
        docs = [_doc("a", "merging branches", "merge branch"), _doc("b", "lonely word")]
        domain = embed_eval.word_domain(docs)
        self.assertIn("merg", domain)  # "merging" and "merge" share the stem
        self.assertIn("branch", domain)
        self.assertNotIn("lonely", domain)  # occurs once

    def test_word_domain_never_crosses_documents(self) -> None:
        docs = [_doc("a", "alpha omega"), _doc("b", "omega alpha"), _doc("c", "omega alpha")]
        domain = embed_eval.word_domain(docs)
        self.assertIn("omega alpha", domain)
        self.assertNotIn("omega omega", domain)

    def test_phrase_domain_dedups_downcases_and_records_sources(self) -> None:
        docs = [_doc("a", "Hello World.", "Second."), _doc("b", "hello world")]
        cands, sources = embed_eval.phrase_domain(docs, lambda raw: raw.split(". "))
        self.assertEqual(cands.count("hello world."), 1)
        self.assertEqual(sources["hello world"], {"b"})
        self.assertEqual(sources["second."], {"a"})


class MathTest(unittest.TestCase):
    """Corrections and statistics."""

    def test_zscore_rows_is_per_candidate(self) -> None:
        rows = embed_eval.zscore_rows([[1.0, 3.0], [5.0, 5.0]])
        self.assertEqual(rows[0], [-1.0, 1.0])
        self.assertEqual(rows[1], [0.0, 0.0])

    def test_center_subtracts_and_renormalizes(self) -> None:
        self.assertEqual(embed_eval.center([2.0, 1.0], [1.0, 1.0]), [1.0, 0.0])

    def test_skewness_sign(self) -> None:
        self.assertEqual(embed_eval.skewness([1, 1, 1]), 0.0)
        self.assertGreater(embed_eval.skewness([0, 0, 0, 0, 10]), 0.0)
        self.assertAlmostEqual(embed_eval.skewness([1, 2, 3]), 0.0)


class HitTest(unittest.TestCase):
    """Gold judging."""

    def test_label_hit_is_membership(self) -> None:
        self.assertTrue(embed_eval._is_hit("L", "cc756c32", "git worktrees"))
        self.assertFalse(embed_eval._is_hit("L", "cc756c32", "vector search"))

    def test_mined_hit_is_stemmed_term_overlap(self) -> None:
        self.assertTrue(embed_eval._is_hit("W", "cc756c32", "stale worktrees"))
        self.assertFalse(embed_eval._is_hit("P", "cc756c32", "send invoices"))


class EvaluateTest(unittest.TestCase):
    """End to end over a synthetic corpus with the bag-of-words fake."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = embed_eval.evaluate(fake_nlce.BowEmbedder(), _corpus(), hubness_k=2)

    def test_every_cell_is_present(self) -> None:
        for domain in embed_eval.DOMAINS:
            for correction in embed_eval.CORRECTIONS:
                cell = self.result["domains"][domain][correction]
                for key in ("spread", "hubness_skew", "p_at_1", "p_at_3", "hit_at_3"):
                    self.assertIn(key, cell)
        self.assertIn("anisotropy", self.result["space"]["raw"])
        self.assertNotIn("anisotropy", self.result["space"]["z"])

    def test_length_bias_margin_is_relevant_minus_long_irrelevant(self) -> None:
        bias = self.result["space"]["raw"]["length_bias"]
        series = bias["series"]
        self.assertAlmostEqual(
            bias["inversion_margin"],
            series["audio metadata"] - series[embed_eval.LENGTH_IRRELEVANT[-1]],
        )
        # Bag of words: the target shares "audio" and "metadata", never "git".
        self.assertGreater(bias["inversion_margin"], 0.0)

    def test_phrase_domain_excludes_self_sourced_candidates(self) -> None:
        top = self.result["domains"]["P"]["raw"]["top3"]["a46c04b0"]
        texts = [text for text, _score in top]
        self.assertEqual(len(texts), 3)
        self.assertNotIn("flac audio metadata", texts)
        # Also mined from ffff0000, but present in the subject: still a self-match.
        self.assertNotIn("use audio tags", texts)

    def test_label_domain_reports_mean_and_sd(self) -> None:
        labels = self.result["domains"]["L"]["raw"]["labels"]
        self.assertEqual(set(labels), set(embed_eval.LABELS))
        self.assertTrue(all(v["sd"] >= 0.0 for v in labels.values()))

    def test_meta_records_space_and_timing(self) -> None:
        meta = self.result["meta"]
        self.assertEqual(meta["fingerprint"], fake_nlce.FINGERPRINT)
        self.assertEqual(meta["documents"], 4)
        self.assertIn("candidates", meta["embed_seconds"])
        self.assertEqual(meta["subjects_found"], ["a31d8f24", "a46c04b0", "cc756c32"])

    def test_chunk_granularity_scores_max_over_windows(self) -> None:
        result = embed_eval.evaluate(
            fake_nlce.BowEmbedder(),
            _corpus(),
            domains=["L"],
            corrections=["raw"],
            granularity="chunk",
        )
        self.assertIn("chunks", result["meta"]["embed_seconds"])
        whole = self.result["space"]["raw"]["length_bias"]["series"]["flac"]
        chunk = result["space"]["raw"]["length_bias"]["series"]["flac"]
        self.assertGreaterEqual(chunk, whole)

    def test_spike_check_pairs_recorded_and_measured(self) -> None:
        rows = embed_eval.spike_check(self.result)
        names = [row[0] for row in rows]
        self.assertIn("length 'git'", names)
        for _name, spike, got, delta in rows:
            self.assertTrue(math.isclose(delta, got - spike))


class LoadCorpusTest(unittest.TestCase):
    """Corpus selection by as-of instant and Id prefix."""

    def _load(self, **kwargs):
        rows = [
            {"Id": "aaaa1", "update_dt": "2026-08-01T00:00:00Z", "Summary": {"raw": "old"}},
            {"Id": "bbbb1", "update_dt": "2026-09-01T00:00:00Z", "Summary": {"raw": "new"}},
            {
                "Id": "cccc1",
                "update_dt": "2026-07-01T00:00:00Z",
                "Summary": {"raw": "x"},
                "Body": {"raw": "y"},
            },
        ]
        store = unittest.mock.Mock()
        store.list_all.return_value = rows
        with unittest.mock.patch("todo_store.get_store", return_value=store):
            return [d.doc_id for d in embed_eval.load_corpus(**kwargs)]

    def test_as_of_include_exclude(self) -> None:
        self.assertEqual(self._load(), ["aaaa1", "bbbb1", "cccc1"])
        self.assertEqual(self._load(as_of="2026-08-05T00:00:00Z"), ["aaaa1", "cccc1"])
        self.assertEqual(
            self._load(as_of="2026-08-05T00:00:00Z", include=["bbbb"], exclude=["cccc"]),
            ["aaaa1", "bbbb1"],
        )

    def test_doc_text_is_summary_space_body(self) -> None:
        self.assertEqual(_doc("x", "Sum", "Body").text, "Sum Body")


if __name__ == "__main__":
    unittest.main()
