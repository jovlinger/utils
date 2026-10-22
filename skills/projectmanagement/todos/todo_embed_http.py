"""OpenAI-compatible HTTP embedder client (Ollama, HF TEI, or any server that
serves ``POST /v1/embeddings``).

Model and runtime are configuration, not code: the same class talks to any
server speaking the OpenAI embeddings protocol. Each model may need its own
query and document prefixes (nomic: ``search_query: `` / ``search_document: ``;
instruction-style prompts for Qwen3 and EmbeddingGemma; none for BGE documents),
so the prefixes are constructor arguments and are part of the fingerprint.

Two entry points, because the prefix differs by side:

* ``embed(text)`` -- a stored text (document side), document prefix applied.
* ``embed_query(text)`` -- a search query, query prefix applied.

Vectors are l2-normalized on this side, and the fingerprint says so.

The fingerprint is ``runtime + model id + weight digest + dim + prefix scheme``.
Changing any one of them yields a different fingerprint, so stored vectors from
the old space are never compared against the new one.

The transport is injectable: the default uses ``urllib``; tests pass a fake that
records requests and returns canned responses, so nothing touches the network.
"""

from __future__ import annotations

import hashlib
import json
import math
import urllib.error
import urllib.request
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from todo_embed import Embedder

ENDPOINT_PATH = "/v1/embeddings"

# transport(url, body, headers) -> (status, response_bytes). Raises OSError (or a
# subclass) when the server cannot be reached.
Transport = Callable[[str, bytes, Dict[str, str]], Tuple[int, bytes]]


def urllib_transport(timeout: float) -> Transport:
    """Default transport: POST via urllib; HTTP error statuses are returned, not raised."""

    def send(url: str, body: bytes, headers: Dict[str, str]) -> Tuple[int, bytes]:
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read()

    return send


def prefix_scheme(query_prefix: str, document_prefix: str) -> str:
    """Short stable tag for a prefix pair; differs whenever either prefix differs."""
    raw = f"{query_prefix}\0{document_prefix}".encode("utf-8")
    return "pfx-" + hashlib.sha256(raw).hexdigest()[:12]


def _l2_normalize(values: Sequence[float]) -> List[float]:
    norm = math.sqrt(sum(v * v for v in values))
    if norm == 0.0:
        return list(values)
    return [v / norm for v in values]


class HttpEmbedder(Embedder):
    """Embedder backed by an OpenAI-compatible ``/v1/embeddings`` server."""

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        dim: int,
        runtime: str,
        weight_digest: str,
        query_prefix: str = "",
        document_prefix: str = "",
        timeout: float = 30.0,
        transport: Optional[Transport] = None,
    ) -> None:
        if dim <= 0:
            raise ValueError(f"dim must be positive, got {dim}")
        self._url = base_url.rstrip("/") + ENDPOINT_PATH
        self._model = model
        self._dim = dim
        self._runtime = runtime
        self._digest = weight_digest
        self._query_prefix = query_prefix
        self._document_prefix = document_prefix
        self._transport = transport if transport is not None else urllib_transport(timeout)

    def fingerprint(self) -> str:
        scheme = prefix_scheme(self._query_prefix, self._document_prefix)
        return (
            f"http:{self._runtime}:{self._model}:digest={self._digest}"
            f":dim={self._dim}:{scheme}:norm=l2:v1"
        )

    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        return self._request(self._document_prefix + text)

    def embed_query(self, text: str) -> List[float]:
        return self._request(self._query_prefix + text)

    def _request(self, payload_text: str) -> List[float]:
        body = json.dumps({"model": self._model, "input": payload_text}).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        try:
            status, raw = self._transport(self._url, body, headers)
        except OSError as exc:
            raise RuntimeError(f"embedding server unreachable at {self._url}: {exc}") from exc
        if status != 200:
            snippet = raw[:200].decode("utf-8", errors="replace")
            raise RuntimeError(f"embedding server returned HTTP {status}: {snippet}")
        return self._parse(raw)

    def _parse(self, raw: bytes) -> List[float]:
        try:
            doc = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("embedding server returned non-JSON body") from exc
        data = doc.get("data") if isinstance(doc, dict) else None
        if not isinstance(data, list) or len(data) != 1:
            raise RuntimeError("embedding response must carry exactly one 'data' item")
        item = data[0]
        vector = item.get("embedding") if isinstance(item, dict) else None
        if not isinstance(vector, list) or not all(
            isinstance(x, (int, float)) and not isinstance(x, bool) for x in vector
        ):
            raise RuntimeError("embedding response item has no numeric 'embedding' list")
        if len(vector) != self._dim:
            raise RuntimeError(
                f"embedding dimension {len(vector)} does not match configured dim {self._dim}"
            )
        return _l2_normalize([float(x) for x in vector])
