# Local embedder research for todo vector search

Phase D evaluated three embedding approaches for indexing `Summary.raw` and
`Body.raw` and ranking `todo.py search` results.

## Candidates

| Embedder | Implementation | Vector dim | ML deps | Platform |
|----------|----------------|------------|---------|----------|
| Apple NLContextualEmbedding | OS framework (Swift/ObjC bridge) | 512-768 | None (OS model assets) | macOS 14+, iOS 17+ only |
| HashEmbedder (default) | Bag-of-words MD5 buckets + L2 norm | 128 | None | Any Python 3 |
| sentence-transformers MiniLM | `all-MiniLM-L6-v2` via PyTorch | 384 | torch, transformers, ST | Any Python 3 with wheels |

### Apple NLContextualEmbedding

Apple's `NaturalLanguage.NLContextualEmbedding` provides on-device contextual
embeddings (WWDC 2023+). Strengths: strong semantic quality, privacy, no pip
install. Weaknesses for this CLI:

- No stable CPython API; requires Swift/ObjC glue or a separate helper binary.
- Model assets download on first use (`requestAssets`); CI and Linux agents lack
  the framework entirely.
- Token-level output needs mean-pooling before ticket-level vectors.

**Verdict:** Built as an opt-in macOS-native sidecar (see below), not the
cross-platform default. It gives the best semantic quality of the three when
available.

**Now implemented** as the `apple` backend (`todo_embed_apple.AppleEmbedder`):

- A Swift sidecar (`apple_embedder/nlce_embed.swift`, built to `nlce-embed` via
  `make apple-embedder`) loads the on-device model and mean-pools + L2-normalizes
  its per-token vectors. Python talks to it over JSON lines.
- Long-lived but **lazily started** on the first `embed()`, since embedding is
  rare next to other todo operations but the model load (and one-time asset
  download) is expensive. One transparent respawn if the sidecar dies.
- Its `fingerprint()` records the model identifier and Apple's integer
  `revision` plus this code's pooling version, e.g.
  `apple_nlce:<modelid>:r1:pool=mean:norm=l2:v1`, so vectors are only compared
  within the exact space that produced them.
- Gated behind `TODO_ENABLE_APPLE_EMBEDDER=1` (listing) and selected with
  `TODO_EMBEDDER=apple`; requires macOS 14+ and the built binary. Verified
  end-to-end: 512-dim vectors, related text ranks above unrelated.

### HashEmbedder (local, default)

`HashEmbedder` in `todo_embed.py` tokenizes text, hashes each token into one of
128 buckets, counts bucket hits, and L2-normalizes. It is the **local embedder**
for this project: zero ML dependencies, deterministic, fast, and good enough
when combined with lexical phrase/token boosts in `search_tickets()`.

Properties:

- Stable key suffix: `"hash"` on Summary/Body and in the `embeddings` table.
- Works offline in CI and agent sandboxes without GPU or model downloads.
- Limitation: no cross-lingual or deep semantic similarity; lexical boost carries
  recall for exact phrases.

**Verdict:** Default via `TODO_EMBEDDER=hash` (also the default when unset).

### sentence-transformers MiniLM

`SentenceTransformerEmbedder` wraps `all-MiniLM-L6-v2` when
`TODO_ENABLE_ST_EMBEDDER=1` and `TODO_EMBEDDER=sentence_transformers`. Strengths:
much better semantic ranking for paraphrases. Weaknesses: large install (~400MB+),
slow cold start, unsuitable for bare CI runners.

**Verdict:** Opt-in for developer machines with `TODO_ENABLE_ST_EMBEDDER=1`.

## Recommendation

| Environment | Embedder | Env vars |
|-------------|----------|----------|
| CI / agents / default | `hash` | (none) |
| Developer semantic search | `sentence_transformers` | `TODO_ENABLE_ST_EMBEDDER=1`, `TODO_EMBEDDER=sentence_transformers` |
| macOS 14+ semantic search | `apple` (NLContextualEmbedding sidecar) | `TODO_ENABLE_APPLE_EMBEDDER=1`, `TODO_EMBEDDER=apple` (after `make apple-embedder`) |

## Storage and search

Vectors are stored as float blobs in `embeddings(ticket_id, field_path,
embedder, vector)`. On ticket write, `_apply_embeddings_to_ticket()` sets
`Summary["hash"]` / `Body["hash"]` (or the active embedder name) and syncs
sqlite rows.

### In-DB vector search (sqlite-vec): deferred

Similarity ranking runs entirely in Python: `todo_embed.cosine_similarity()`
over the float blobs unpacked from the `embeddings` table. The sqlite-vec
extension (`vec0`) was evaluated and intentionally **not** adopted for now:

- It is a performance/ergonomics play, not a quality one -- it computes the same
  exact cosine over the same vectors, so ranking is unchanged. Relevance is set
  by the embedder, not by where the distance math runs.
- It only pays off at thousands-to-millions of vectors; the current corpus makes
  the Python scan effectively instant.
- It also needs a CPython built with loadable-extension support, which is absent
  on the macOS system/venv interpreters here.

Store the vector as a plain packed-float array and rank in Python. Revisit an
in-DB `vec0` search path only when the index grows enough to justify it.

## Configuration summary

```text
TODO_EMBEDDER=hash                    # default
TODO_ENABLE_ST_EMBEDDER=1             # expose sentence_transformers in help
TODO_EMBEDDER=sentence_transformers   # opt-in ML backend
TODO_ENABLE_APPLE_EMBEDDER=1          # expose the macOS apple backend in help
TODO_EMBEDDER=apple                   # opt-in macOS NLContextualEmbedding sidecar
TODO_APPLE_NLCE_BIN=/path/to/nlce-embed  # override the sidecar binary location
```
