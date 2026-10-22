"""HTTP embedder for OpenAI-compatible ``POST /v1/embeddings`` servers.

Ollama and HF TEI both serve this endpoint, so runtime and model are
configuration, not code. Asymmetric models need a per-role prefix on the text
(``search_query: `` vs ``search_document: `` for nomic, instruction prompts for
Qwen3 / EmbeddingGemma, none for BGE documents); ``embed_query`` and
``embed_document`` apply it, and plain ``embed`` is the document role.

The fingerprint is ``http:<runtime>:<model>:<weight digest>:d<dim>:<prefix
scheme>:<processing version>``; swapping any piece invalidates stored vectors.
Stdlib ``urllib`` only; no network access happens until the first embed.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Dict, List, Optional, Tuple

from todo_embed import Embedder

# Bump when this client's request/response handling changes the vectors.
_PROCESSING_VERSION = "v1"

# scheme name -> (query prefix, document prefix)
PREFIX_SCHEMES: Dict[str, Tuple[str, str]] = {
    "none": ("", ""),
    "nomic": ("search_query: ", "search_document: "),
    "bge": (
        "Represent this sentence for searching relevant passages: ",
        "",
    ),
    "qwen3": (
        "Instruct: Given a search query, retrieve relevant passages that "
        "answer the query\nQuery: ",
        "",
    ),
    "embeddinggemma": ("task: search result | query: ", "title: none | text: "),
}


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
        prefix_scheme: str = "none",
        query_prefix: Optional[str] = None,
        document_prefix: Optional[str] = None,
        weight_digest: str = "unknown",
        dim: Optional[int] = None,
        timeout: float = 60.0,
        processing_version: str = _PROCESSING_VERSION,
    ) -> None:
        if prefix_scheme not in PREFIX_SCHEMES and (
            query_prefix is None or document_prefix is None
        ):
            raise HttpEmbedderError(f"unknown prefix scheme {prefix_scheme!r}")
        default_q, default_d = PREFIX_SCHEMES.get(prefix_scheme, ("", ""))
        self._query_prefix = default_q if query_prefix is None else query_prefix
        self._document_prefix = default_d if document_prefix is None else document_prefix
        self._url = base_url.rstrip("/") + "/v1/embeddings"
        self._model = model
        self._runtime = runtime
        self._prefix_scheme = prefix_scheme
        self._weight_digest = weight_digest
        self._dim = dim
        self._timeout = timeout
        self._processing_version = processing_version

    # -- io ----------------------------------------------------------------

    def _post(self, text: str) -> List[float]:
        body = json.dumps({"model": self._model, "input": text}).encode("utf-8")
        req = urllib.request.Request(
            self._url, data=body, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise HttpEmbedderError(f"{self._url} returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise HttpEmbedderError(f"cannot reach {self._url}: {exc}") from exc
        except ValueError as exc:
            raise HttpEmbedderError(f"{self._url} sent non-JSON") from exc
        try:
            vector = payload["data"][0]["embedding"]
        except (KeyError, IndexError, TypeError) as exc:
            raise HttpEmbedderError(f"malformed embeddings reply: {payload!r}") from exc
        if not isinstance(vector, list) or not vector:
            raise HttpEmbedderError(f"malformed embeddings reply: {payload!r}")
        result = [float(x) for x in vector]
        if self._dim is None:
            self._dim = len(result)
        elif len(result) != self._dim:
            raise HttpEmbedderError(f"expected dim {self._dim}, server returned {len(result)}")
        return result

    # -- Embedder ----------------------------------------------------------

    def fingerprint(self) -> str:
        return (
            f"http:{self._runtime}:{self._model}:{self._weight_digest}"
            f":d{self.dimension()}:prefix={self._prefix_scheme}"
            f":{self._processing_version}"
        )

    def dimension(self) -> int:
        if self._dim is None:
            self._post(self._document_prefix + "dimension probe")
        assert self._dim is not None
        return self._dim

    def embed_query(self, text: str) -> List[float]:
        return self._post(self._query_prefix + text)

    def embed_document(self, text: str) -> List[float]:
        return self._post(self._document_prefix + text)

    def embed(self, text: str) -> List[float]:
        return self.embed_document(text)
