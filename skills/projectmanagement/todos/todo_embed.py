"""Pluggable text embedders for todo vector search."""

from __future__ import annotations

import hashlib
import math
import os
import struct
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional, Sequence, Type

JsonDict = dict


class Embedder(ABC):
    """Abstract text embedder."""

    @abstractmethod
    def fingerprint(self) -> str:
        """Stable identity of the vector space this embedder produces.

        Persisted as the ``embedder`` column in the ``embeddings`` table and as
        the per-field key in Summary/Body, so only vectors sharing a fingerprint
        are ever compared. It must capture everything that changes the vector:
        the model, the model's own revision, and this code's processing
        (pooling, normalization). Bump it whenever any of those change.
        """

    @abstractmethod
    def dimension(self) -> int:
        """Vector length."""

    @abstractmethod
    def embed(self, text: str) -> List[float]:
        """Embed one text string."""


class NullEmbedder(Embedder):
    """Zero vector embedder for disabled search paths."""

    def __init__(self, dim: int = 8) -> None:
        self._dim = dim

    def fingerprint(self) -> str:
        return "null"

    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        return [0.0] * self._dim


class MockEmbedder(Embedder):
    """Deterministic hash-based embedder for tests."""

    def __init__(self, dim: int = 16) -> None:
        self._dim = dim

    def fingerprint(self) -> str:
        return "mock"

    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        needed = self._dim * 4
        buf = (digest * ((needed // len(digest)) + 1))[:needed]
        values = list(struct.unpack(f"<{self._dim}f", buf))
        return _normalize(values)


class HashEmbedder(Embedder):
    """Low-resource local embedder: bag-of-words hashing into a fixed vector."""

    def __init__(self, dim: int = 128) -> None:
        self._dim = dim

    def fingerprint(self) -> str:
        return "hash"

    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        vec = [0.0] * self._dim
        for token in _tokenize(text):
            bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self._dim
            vec[bucket] += 1.0
        return _normalize(vec)


class SentenceTransformerEmbedder(Embedder):
    """Optional sentence-transformers backend when installed."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "sentence-transformers is not installed; use hash or mock embedder"
            ) from exc
        self._model_name = model_name
        self._model = SentenceTransformer(model_name)
        sample = self._model.encode("test", normalize_embeddings=True)
        self._dim = len(sample)

    def fingerprint(self) -> str:
        safe = self._model_name.replace("/", "_")
        return f"st_{safe}"

    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        vector = self._model.encode(text, normalize_embeddings=True)
        return [float(x) for x in vector]


_REGISTRY: Dict[str, Type[Embedder]] = {
    "null": NullEmbedder,
    "mock": MockEmbedder,
    "hash": HashEmbedder,
}


class _OptionalBackend:
    """An embedder offered only when its enable flag is set.

    Kept out of the always-available registry because it needs a heavy or
    platform-specific dependency (ML wheels, a native sidecar). It is listed by
    ``available_embedders()`` only when ``$enable_env == "1"``, and ``factory``
    imports the dependency lazily so importing ``todo_embed`` never drags it in.
    Selecting it by exact key still instantiates even when the flag is unset, so
    the factory may still raise if the platform/dependency is missing.
    """

    def __init__(self, key: str, enable_env: str, factory: Callable[[], Embedder]) -> None:
        self.key = key
        self.enable_env = enable_env
        self.factory = factory


def _make_sentence_transformers() -> Embedder:
    return SentenceTransformerEmbedder()


def _make_apple() -> Embedder:
    from todo_embed_apple import AppleEmbedder  # lazy: keeps todo_embed platform-free

    return AppleEmbedder()


_OPTIONAL: Dict[str, _OptionalBackend] = {
    "sentence_transformers": _OptionalBackend(
        "sentence_transformers", "TODO_ENABLE_ST_EMBEDDER", _make_sentence_transformers
    ),
    "apple": _OptionalBackend("apple", "TODO_ENABLE_APPLE_EMBEDDER", _make_apple),
}


def register_embedder(name: str, cls: Type[Embedder]) -> None:
    """Register an always-available embedder implementation by selection key."""
    _REGISTRY[name] = cls


def available_embedders() -> List[str]:
    """Return selectable embedder keys: always-on plus any enabled optional ones."""
    names = sorted(_REGISTRY.keys())
    for backend in _OPTIONAL.values():
        if os.environ.get(backend.enable_env) == "1":
            names.append(backend.key)
    return names


def get_embedder(name: Optional[str] = None) -> Embedder:
    """Instantiate the configured embedder by selection key."""
    chosen = name or os.environ.get("TODO_EMBEDDER", "hash")
    backend = _OPTIONAL.get(chosen)
    if backend is not None:
        return backend.factory()
    cls = _REGISTRY.get(chosen)
    if cls is None:
        raise ValueError(f"unknown embedder {chosen!r}; choose from {available_embedders()}")
    return cls()


def cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity between two vectors."""
    if len(a) != len(b) or not a:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def _normalize(values: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0.0:
        return list(values)
    return [v / norm for v in values]


def _tokenize(text: str) -> List[str]:
    return [part.lower() for part in text.split() if part.strip()]
