"""Pluggable text embedders for todo vector search."""

from __future__ import annotations

import hashlib
import math
import struct
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Sequence, Tuple

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


class _Backend:
    """Registry entry for one selectable embedder.

    Flags live here, not on the class, so listing and selection never import an
    optional backend just to read its metadata. ``factory`` imports any heavy or
    platform-specific dependency lazily.

    ``cheap``: cheap enough to auto-populate on every write (kept always-current).
    ``hidden``: excluded from the default "all" set and from ``embedders``
    listing, but still selectable by exact key -- test doubles (``null``,
    ``mock``) and opt-in backends (``st``) that we do not advertise.
    """

    def __init__(
        self,
        key: str,
        factory: Callable[[], "Embedder"],
        *,
        cheap: bool = False,
        hidden: bool = False,
    ) -> None:
        self.key = key
        self.factory = factory
        self.cheap = cheap
        self.hidden = hidden


def _make_sentence_transformers() -> Embedder:
    return SentenceTransformerEmbedder()


def _make_apple() -> Embedder:
    from todo_embed_apple import AppleEmbedder  # lazy: keeps todo_embed platform-free

    return AppleEmbedder()


# Insertion order defines the default "all" order (non-hidden entries).
_BACKENDS: Dict[str, _Backend] = {
    "hash": _Backend("hash", HashEmbedder, cheap=True),
    "apple": _Backend("apple", _make_apple),
    "st": _Backend("st", _make_sentence_transformers, hidden=True),
    "mock": _Backend("mock", MockEmbedder, hidden=True),
    "null": _Backend("null", NullEmbedder, hidden=True),
}


def register_embedder(
    key: str,
    factory: Callable[[], Embedder],
    *,
    cheap: bool = False,
    hidden: bool = False,
) -> None:
    """Register a selectable embedder by key."""
    _BACKENDS[key] = _Backend(key, factory, cheap=cheap, hidden=hidden)


def default_embedder_names() -> List[str]:
    """Selection keys in the default 'all' set: every non-hidden embedder."""
    return [b.key for b in _BACKENDS.values() if not b.hidden]


def available_embedders() -> List[str]:
    """Non-hidden selection keys, for user-facing 'choose from' messages."""
    return default_embedder_names()


def list_embedders() -> List[Tuple[str, bool, bool]]:
    """Return ``(key, cheap, hidden)`` for every registered embedder, in order."""
    return [(b.key, b.cheap, b.hidden) for b in _BACKENDS.values()]


def cheap_embedders() -> List[Embedder]:
    """Instantiate the cheap embedders -- the ones auto-populated on write."""
    return [b.factory() for b in _BACKENDS.values() if b.cheap]


def get_embedder(name: str) -> Embedder:
    """Instantiate an embedder by exact selection key.

    Raises ``ValueError`` for an unknown key; the backend's own factory may raise
    ``RuntimeError`` (e.g. missing sidecar/wheels) when the dependency is absent.
    """
    backend = _BACKENDS.get(name)
    if backend is None:
        raise ValueError(f"unknown embedder {name!r}; choose from {available_embedders()}")
    return backend.factory()


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
