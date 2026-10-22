"""HTTP embedder: any runtime serving the OpenAI-compatible ``POST /v1/embeddings``.

Ollama and Hugging Face text-embeddings-inference (TEI) both serve this endpoint,
so the model and the runtime are configuration, not code::

    ->  POST {base_url}/v1/embeddings  {"model": "<id>", "input": ["text", ...]}
    <-  {"data": [{"index": 0, "embedding": [float, ...]}, ...]}

Embedding models are asymmetric: a short query and a long document are meant to
be encoded with different prefixes (nomic ``search_query: `` / ``search_document: ``,
Qwen3 and EmbeddingGemma instruction prompts, BGE v1.5 a query instruction only).
A ``PrefixScheme`` carries that pair; ``embed_query`` / ``embed_document`` apply
it, and ``embed`` (the ``Embedder`` interface) uses the document side unless
``default_role="query"`` is given.

The fingerprint records everything that changes a vector -- runtime, model id,
weight digest, dimension, prefix scheme (name plus a hash of its exact strings)
and this code's normalization -- so swapping any of them invalidates stored
vectors. The weight digest is passed in, or read from the runtime: Ollama's
``GET /api/tags`` (``digest`` of the matching model) or TEI's ``GET /info``
(``model_sha``). An embedder whose digest cannot be established refuses to
fingerprint rather than invent one.

Stdlib only (``urllib``); no network is touched until the first call.
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from typing import Any, Dict, List, Mapping, Optional, Sequence, Union

from todo_embed import Embedder

# Bump when request/normalization handling changes: it is part of the fingerprint.
_PROCESSING_VERSION = "v1"

_ROLES = ("query", "document")
_DIM_PROBE = "dimension probe"


class HttpEmbedderError(RuntimeError):
    """HTTP embedder backend failure."""


class PrefixScheme:
    """The query/document prefixes one model family expects."""

    def __init__(self, name: str, query: str = "", document: str = "") -> None:
        self.name = name
        self.query = query
        self.document = document

    def apply(self, role: str, text: str) -> str:
        """Prefix *text* for *role* (``query`` or ``document``)."""
        if role == "query":
            return self.query + text
        if role == "document":
            return self.document + text
        raise ValueError(f"unknown role {role!r}; choose from {list(_ROLES)}")

    def tag(self) -> str:
        """``name-hash8``: the scheme's fingerprint component.

        The hash covers the exact strings, so editing a prefix in place changes the
        fingerprint even when the name stays.
        """
        payload = json.dumps([self.query, self.document]).encode("utf-8")
        return f"{self.name}-{hashlib.sha256(payload).hexdigest()[:8]}"


_QWEN3_TASK = "Given a web search query, retrieve relevant passages that answer the query"

# Strings are the ones each model card specifies.
PREFIX_SCHEMES: Dict[str, PrefixScheme] = {
    "none": PrefixScheme("none"),
    "nomic": PrefixScheme("nomic", "search_query: ", "search_document: "),
    "qwen3": PrefixScheme("qwen3", f"Instruct: {_QWEN3_TASK}\nQuery:", ""),
    "embeddinggemma": PrefixScheme(
        "embeddinggemma", "task: search result | query: ", "title: none | text: "
    ),
    "bge-en-v1.5": PrefixScheme(
        "bge-en-v1.5", "Represent this sentence for searching relevant passages: ", ""
    ),
}


def get_prefix_scheme(name: str) -> PrefixScheme:
    """Look up a registered prefix scheme by name."""
    scheme = PREFIX_SCHEMES.get(name)
    if scheme is None:
        raise ValueError(f"unknown prefix scheme {name!r}; choose from {sorted(PREFIX_SCHEMES)}")
    return scheme


def _l2(values: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0.0:
        raise HttpEmbedderError("runtime returned a zero vector")
    return [v / norm for v in values]


class HttpEmbedder(Embedder):
    """Embed text through an OpenAI-compatible ``/v1/embeddings`` endpoint."""

    def __init__(  # pylint: disable=too-many-arguments
        self,
        base_url: str,
        model: str,
        *,
        runtime: str,
        prefix: Union[str, PrefixScheme] = "none",
        digest: Optional[str] = None,
        default_role: str = "document",
        batch_size: int = 32,
        timeout: float = 120.0,
    ) -> None:
        if default_role not in _ROLES:
            raise ValueError(f"unknown role {default_role!r}; choose from {list(_ROLES)}")
        if batch_size < 1:
            raise ValueError("batch_size must be >= 1")
        self._base = base_url.rstrip("/")
        self._model = model
        self._runtime = runtime
        self._scheme = get_prefix_scheme(prefix) if isinstance(prefix, str) else prefix
        self._digest = digest
        self._default_role = default_role
        self._batch_size = batch_size
        self._timeout = timeout
        self._dim: Optional[int] = None

    # -- io ----------------------------------------------------------------

    def _http(self, method: str, path: str, body: Optional[Mapping[str, Any]] = None) -> Any:
        url = self._base + path
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            raise HttpEmbedderError(f"{method} {url}: HTTP {exc.code}: {detail}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise HttpEmbedderError(f"{method} {url}: {exc}") from exc
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HttpEmbedderError(f"{method} {url}: non-JSON reply {raw[:200]!r}") from exc

    def _post_embeddings(self, inputs: Sequence[str]) -> List[List[float]]:
        reply = self._http("POST", "/v1/embeddings", {"model": self._model, "input": list(inputs)})
        data = reply.get("data") if isinstance(reply, dict) else None
        if not isinstance(data, list) or len(data) != len(inputs):
            raise HttpEmbedderError(
                f"embeddings reply has {len(data) if isinstance(data, list) else 'no'} "
                f"items for {len(inputs)} inputs"
            )
        try:
            ordered = sorted(data, key=lambda item: int(item["index"]))
            vectors = [[float(x) for x in item["embedding"]] for item in ordered]
        except (KeyError, TypeError, ValueError) as exc:
            raise HttpEmbedderError(f"malformed embeddings reply: {exc}") from exc
        if [int(item["index"]) for item in ordered] != list(range(len(inputs))):
            raise HttpEmbedderError("embeddings reply indexes are not 0..n-1")
        return vectors

    def _discover_digest(self) -> str:
        if self._runtime == "ollama":
            reply = self._http("GET", "/api/tags")
            models = reply.get("models", []) if isinstance(reply, dict) else []
            names = {self._model}
            if ":" not in self._model:
                names.add(self._model + ":latest")
            for entry in models:
                if isinstance(entry, dict) and (
                    entry.get("name") in names or entry.get("model") in names
                ):
                    digest = entry.get("digest")
                    if isinstance(digest, str) and digest:
                        return digest
            raise HttpEmbedderError(f"ollama /api/tags lists no digest for model {self._model!r}")
        if self._runtime == "tei":
            reply = self._http("GET", "/info")
            digest = reply.get("model_sha") if isinstance(reply, dict) else None
            if isinstance(digest, str) and digest:
                return digest
            raise HttpEmbedderError("tei /info reports no model_sha; pass digest= explicitly")
        raise HttpEmbedderError(
            f"cannot discover a weight digest for runtime {self._runtime!r}; pass digest= explicitly"
        )

    # -- embedding ---------------------------------------------------------

    def embed_texts(self, texts: Sequence[str], role: Optional[str] = None) -> List[List[float]]:
        """Embed *texts* for *role* in batches; l2-normalized, one vector per text."""
        role = role or self._default_role
        prefixed = [self._scheme.apply(role, t) for t in texts]
        out: List[List[float]] = []
        for start in range(0, len(prefixed), self._batch_size):
            for vec in self._post_embeddings(prefixed[start : start + self._batch_size]):
                if self._dim is None:
                    self._dim = len(vec)
                elif len(vec) != self._dim:
                    raise HttpEmbedderError(
                        f"runtime returned a {len(vec)}-d vector, expected {self._dim}"
                    )
                out.append(_l2(vec))
        return out

    def embed_query(self, text: str) -> List[float]:
        """Embed one short query-side text (label, search terms)."""
        return self.embed_texts([text], "query")[0]

    def embed_document(self, text: str) -> List[float]:
        """Embed one document-side text (todo Summary/Body)."""
        return self.embed_texts([text], "document")[0]

    # -- Embedder ----------------------------------------------------------

    def fingerprint(self) -> str:
        if self._digest is None:
            self._digest = self._discover_digest()
        return (
            f"http:{self._runtime}:{self._model}:{self._digest}:d{self.dimension()}"
            f":prefix={self._scheme.tag()}:norm=l2:{_PROCESSING_VERSION}"
        )

    def dimension(self) -> int:
        if self._dim is None:
            self.embed_texts([_DIM_PROBE])
        assert self._dim is not None
        return self._dim

    def embed(self, text: str) -> List[float]:
        return self.embed_texts([text])[0]
