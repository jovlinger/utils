"""Unit tests for the embedder compression eval harness (no CLI, no network)."""

import math

import eval_embedder_compression as E
import todo_embed


def _docs():
    docs = [
        E.Doc(
            s[0] + "0" * 56,
            "2026-01-01T00:00:00Z",
            "done",
            f"{s[1]} summary",
            f"{s[3][0]} body. second line about {s[3][-1]}.",
        )
        for s in E.SUBJECTS
    ]
    docs.append(
        E.Doc("f" * 64, "2026-01-02T00:00:00Z", "done", "filler", "unrelated text. more text.")
    )
    return docs


def test_math_helpers():
    assert math.isclose(E.dot([1, 2], [3, 4]), 11)
    assert math.isclose(math.sqrt(E.dot(E.normalize([3, 4]), E.normalize([3, 4]))), 1.0)
    assert E.zscores([1.0, 1.0]) == [0.0, 0.0]
    z = E.zscores([1.0, 2.0, 3.0])
    assert math.isclose(sum(z), 0.0, abs_tol=1e-12)
    assert E.skewness([1, 1, 1, 10]) > 0
    assert E.skewness([2, 2]) == 0.0


def test_candidates_w_requires_two_documents():
    cands = E.candidates_w(["alpha beta gamma", "alpha beta delta", "epsilon"])
    assert "alpha" in cands and "alpha beta" in cands
    assert "gamma" not in cands and "alpha beta gamma" not in cands


def test_candidates_p_dedups_and_lowercases():
    cands = E.candidates_p(["Alpha. Beta.", "ALPHA. Gamma."])
    assert cands.count("alpha") == 1
    assert "alpha beta" in cands


def test_evaluate_with_mock_embedder_shape():
    result = E.evaluate(todo_embed.MockEmbedder(dim=32), _docs(), domains=("D", "W", "P"))
    assert result["fingerprint"] == "mock"
    assert result["docs"] == 7
    for dom in ("D", "W", "P"):
        for corr in E.CORRECTIONS:
            entry = result["domains"][dom][corr]
            assert 0.0 <= entry["p@1"] <= entry["p@3"] <= 1.0
    assert result["domains"]["D"]["z"]["spread"] is None
    assert result["anisotropy"]["z"] is None
    assert set(result["length_bias"]["raw"]["series"]) >= set(E.RELEVANT_CANDIDATES)
    assert len(result["label_table_raw"]) == len(E.LABELS)


class _RoleEmbedder(todo_embed.MockEmbedder):
    """Asymmetric fake: queries and documents are embedded differently."""

    def embed_query(self, text):
        return self.embed("search_query: " + text)

    def embed_document(self, text):
        return self.embed("search_document: " + text)


def test_roles_are_routed_to_prefixed_methods():
    emb = E.Embedding(_RoleEmbedder())
    assert emb.get("x", "query") == _RoleEmbedder().embed("search_query: x")
    assert emb.get("x", "document") == _RoleEmbedder().embed("search_document: x")
    assert emb.get("x", "query") != emb.get("x", "document")


def test_cache_returns_identical_vectors(tmp_path):
    path = str(tmp_path / "c.db")
    first = E.Embedding(todo_embed.MockEmbedder(), path)
    v1 = first.get("hello", "query")
    first.commit()
    second = E.Embedding(todo_embed.MockEmbedder(), path)
    assert second.get("hello", "query") == v1
    assert second.embed_calls == 0


def test_check_apple_flags_deviation():
    result = E.evaluate(todo_embed.MockEmbedder(dim=32), _docs(), domains=("D",))
    ok, lines = E.check_apple(result)
    assert ok is False
    assert any(line.startswith("FAIL") for line in lines)
