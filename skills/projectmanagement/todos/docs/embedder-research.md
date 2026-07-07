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
- A first-class non-hidden embedder: in the default `search` set and selectable
  as `--embedder apple`. Requires macOS 14+ and the built binary; if it is
  missing, a search that includes it errors (choose `--embedder` explicitly).
  `TODO_APPLE_NLCE_BIN` overrides the binary path. Verified end-to-end: 512-dim
  vectors, related text ranks above unrelated.

### HashEmbedder (local, default)

`HashEmbedder` in `todo_embed.py` tokenizes text, hashes each token into one of
128 buckets, counts bucket hits, and L2-normalizes. It is the **local embedder**
for this project: zero ML dependencies, deterministic, fast, and good enough
when combined with lexical phrase/token boosts in `search_tickets()`.

Properties:

- Stable fingerprint: `"hash"` on Summary/Body and in the `embeddings` table.
- Works offline in CI and agent sandboxes without GPU or model downloads.
- The only `cheap` embedder: auto-populated on every write (see below).
- Limitation: no cross-lingual or deep semantic similarity; the lexical ranker
  carries recall for exact phrases.

**Verdict:** The always-on default; first entry in the `search` default set.

### sentence-transformers MiniLM

`SentenceTransformerEmbedder` wraps `all-MiniLM-L6-v2`. Strengths: much better
semantic ranking for paraphrases. Weaknesses: large install (~400MB+), slow cold
start, unsuitable for bare CI runners.

**Verdict:** Kept as a hidden `st` backend -- selectable by exact name
(`--embedder st`) for developers who install it, but not advertised or in the
default set. Raises at selection time if the package is absent.

## Recommendation

| Environment | Embedder(s) | How |
|-------------|-------------|-----|
| CI / agents | `hash` | `search --embedder hash` (hermetic, no downloads) |
| Default (this machine) | `hash,apple` | `search` with no `--embedder` |
| Developer paraphrase search | `st` | `pip install sentence-transformers`, `search --embedder st` |

## Storage, selection, population, and ranking

Vectors are stored as packed-float blobs in `embeddings(ticket_id, field_path,
embedder, vector)`, keyed by the producing embedder's `fingerprint()`. A copy is
also stamped into the ticket JSON (`Summary[<fingerprint>]`) for `read` display;
search reads only the table.

**Selection.** There is no embedder env var. `search --embedder` takes a comma
list; the default is every non-hidden embedder (`hash,apple` here). `todo.py
embedders` lists them. Requesting an unavailable embedder (including via the
default) errors -- pick one explicitly.

**Population is lazy.** Only `cheap` embedders (`hash`) are computed on write.
When a raw field changes its stored vectors are cleared for all embedders
(`--no-clear` keeps them, for trivial edits); expensive embedders are then
backfilled on demand the first time a `search` uses them (skipped under
`--dry-run`). A ticket still missing a vector just does not contribute to that
embedder's ranking.

**Ranking is reciprocal rank fusion.** Each chosen embedder and a lexical
overlap ranker independently rank the tickets; scores fuse as `sum 1/(k+rank)`
(`_RRF_K=60`). RRF is scale-free, so Apple's high cosine baseline cannot swamp
hash. (Tunable; not load-bearing.)

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

## Usage summary

```text
todo.py embedders                       # list selectable (non-hidden) embedders
todo.py search QUERY                     # default embedders (hash,apple here)
todo.py search QUERY --embedder hash     # hermetic; hard 0-similarity cutoff
todo.py search QUERY --embedder hash,apple --dry-run   # rank existing vectors only
todo.py search QUERY --embedder st       # hidden backend, by exact name
todo.py set --summary "..." --no-clear   # keep vectors despite a trivial raw edit

TODO_APPLE_NLCE_BIN=/path/to/nlce-embed  # override the apple sidecar binary path
make apple-embedder                      # build the sidecar (macOS 14+, swiftc)
```
