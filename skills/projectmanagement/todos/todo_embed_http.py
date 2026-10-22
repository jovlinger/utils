"""OpenAI-compatible HTTP embedder (Ollama, HF TEI, anything serving /v1/embeddings).

One client for every containerized runtime: the runtime, model and prefix
scheme are configuration, not code. Only the stdlib is used.

Request  ``POST <base_url>/v1/embeddings`` with ``{"model": str, "input": [str]}``.
Response ``{"data": [{"index": int, "embedding": [float, ...]}, ...]}``.

Retrieval models are asymmetric: a query and a document are embedded with
different prefixes/instructions. ``embed`` is the document side (what the
``Embedder`` ABC and the stored index use); ``embed_query`` is the query side.
Both L2-normalize the returned vector.

The fingerprint is ``http:<runtime>:<model>:<digest>:d<dim>:<scheme>:<prefix hash>``
so swapping the runtime, the model, its weights, the dimension or the prefixes
invalidates stored vectors. ``digest`` is the model weight digest (Ollama
``/api/show``, TEI ``/info`` ``model_sha``), supplied by the caller.
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Tuple

from todo_embed import Embedder

# scheme name -> (query prefix, document prefix)
PREFIX_SCHEMES: Dict[str, Tuple[str, str]] = {
    "none": ("", ""),
    "nomic": ("search_query: ", "search_document: "),
    "qwen3": (
        "Instruct: Given a web search query, retrieve relevant passages "
        "that answer the query\nQuery: ",
        "",
    ),
    "embeddinggemma": ("task: search result | query: ", "title: none | text: "),
    "bge": ("Represent this sentence for searching relevant passages: ", ""),
}

_PROBE_TEXT = "dimension probe"


class HttpEmbedderError(RuntimeError):
    """HTTP embedder backend failure."""


class HttpEmbedder(Embedder):
    """Embed text through an OpenAI-compatible ``/v1/embeddings`` endpoint."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        runtime: str = "openai",
        digest: str = "unknown",
        prefix_scheme: str = "none",
        timeout: float = 60.0,
        dim: Optional[int] = None,
    ) -> None:
        if prefix_scheme not in PREFIX_SCHEMES:
            raise HttpEmbedderError(
                f"unknown prefix scheme {prefix_scheme!r}; "
                f"known: {', '.join(sorted(PREFIX_SCHEMES))}"
            )
        self._url = base_url.rstrip("/") + "/v1/embeddings"
        self._model = model
        self._runtime = runtime
        self._digest = digest
        self._scheme = prefix_scheme
        self._query_prefix, self._doc_prefix = PREFIX_SCHEMES[prefix_scheme]
        self._timeout = timeout
        self._dim = dim

    def _request(self, text: str) -> List[float]:
        body = json.dumps({"model": self._model, "input": [text]}).encode("utf-8")
        req = urllib.request.Request(
            self._url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload: Any = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:200]
            raise HttpEmbedderError(
                f"{self._url} returned HTTP {exc.code}: {detail}"
            ) from exc
        except (urllib.error.URLError, OSError, ValueError) as exc:
            raise HttpEmbedderError(f"{self._url} request failed: {exc}") from exc
        try:
            vector = [float(x) for x in payload["data"][0]["embedding"]]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise HttpEmbedderError(
                f"{self._url} sent a malformed embeddings response"
            ) from exc
        if not vector:
            raise HttpEmbedderError(f"{self._url} sent an empty embedding")
        if self._dim is not None and len(vector) != self._dim:
            raise HttpEmbedderError(
                f"{self._url} sent dim {len(vector)}, expected {self._dim}"
            )
        norm = math.sqrt(sum(x * x for x in vector))
        if norm == 0.0:
            return vector
        return [x / norm for x in vector]

    def dimension(self) -> int:
        if self._dim is None:
            self._dim = len(self._request(self._doc_prefix + _PROBE_TEXT))
        return self._dim

    def fingerprint(self) -> str:
        prefix_hash = hashlib.sha256(
            json.dumps([self._query_prefix, self._doc_prefix]).encode("utf-8")
        ).hexdigest()[:8]
        return (
            f"http:{self._runtime}:{self._model}:{self._digest}"
            f":d{self.dimension()}:{self._scheme}:{prefix_hash}"
        )

    def embed(self, text: str) -> List[float]:
        """Embed a document (stored side)."""
        return self._request(self._doc_prefix + text)

    def embed_query(self, text: str) -> List[float]:
        """Embed a search query (query side)."""
        return self._request(self._query_prefix + text)
