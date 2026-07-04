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

**Verdict:** Good for a future macOS-native sidecar, not for the cross-platform
todo CLI default.

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
| Future macOS app | NLContextualEmbedding sidecar | TBD |

## Storage and search

Vectors are stored as float blobs in `embeddings(ticket_id, field_path,
embedder, vector)`. On ticket write, `_apply_embeddings_to_ticket()` sets
`Summary["hash"]` / `Body["hash"]` (or the active embedder name) and syncs
sqlite rows.

### sqlite-vec extension (optional)

`todo_db.try_load_sqlite_vec()` attempts to load the sqlite-vec extension
(`vec0`, `sqlite-vec`, or `TODO_SQLITE_VEC_PATH`) at connect time. When loading
fails (typical in CI/Linux), search falls back to Python-side cosine similarity
in `todo_embed.cosine_similarity()` over unpacked blobs. No behavior change is
required for callers; ANN indexing can be wired later when vec is reliably
available.

## Configuration summary

```text
TODO_EMBEDDER=hash                    # default
TODO_ENABLE_ST_EMBEDDER=1             # expose sentence_transformers in help
TODO_EMBEDDER=sentence_transformers   # opt-in ML backend
TODO_SQLITE_VEC_PATH=/path/to/vec0    # optional sqlite-vec load path
```
