# Embedder baselines (todo:1e3c7e0f)

Baseline rows for the embedder compression matrix, produced by `embed_eval.py`
(whole-document granularity, all domains, all corrections). Full results per
embedder sit beside this file as `<embedder>.json`.

Corpus: the full todo store at run time (2026-10-22), 99 documents, no
`--as-of` / `--include` / `--exclude`. z-scored spread columns are n/a: z
normalizes every candidate row to mean 0, sd 1 by construction.

Reproduce:

    TODO_APPLE_NLCE_BIN=<path to built nlce-embed> ./embed_eval.py --embedder apple \
        --out docs/embed-eval/apple.json

## apple

| embedder | fingerprint | dim | docs | W | P | embed s (docs / cands) | wall s |
|---|---|---|---|---|---|---|---|
| apple | `apple_nlce:5C45D94E-BAB4-4927-94B6-8B5745C46289:r1:pool=mean:norm=l2:v1` | 512 | 99 | 8643 | 11119 | 2.2 / 167.0 | 216.0 |

| correction | anisotropy | inversion_margin | 'audio metadata' | 13-word irrelevant |
|---|---|---|---|---|
| raw | +0.9346 | -0.2723 | +0.6040 | +0.8763 |
| centered | -0.0069 | +0.0762 | -0.1384 | -0.2146 |
| z | n/a | +0.9748 | -1.3078 | -2.2825 |

| domain | correction | range | between_sd | within_sd | signal_ratio | hubness_skew | p@1 | p@3 | hit@3 |
|---|---|---|---|---|---|---|---|---|---|
| W | raw | 0.5672 | 0.0815 | 0.0225 | 0.275 | +22.645 | 0.167 | 0.111 | 0.333 |
| W | centered | 0.0276 | 0.0037 | 0.1336 | 36.235 | +7.389 | 0.167 | 0.167 | 0.167 |
| W | z | n/a | n/a | 1.0000 | n/a | +4.717 | 0.167 | 0.167 | 0.167 |
| P | raw | 0.4915 | 0.0591 | 0.0189 | 0.320 | +8.398 | 0.333 | 0.222 | 0.500 |
| P | centered | 0.0587 | 0.0078 | 0.1615 | 20.725 | +5.114 | 0.333 | 0.222 | 0.500 |
| P | z | n/a | n/a | 1.0000 | n/a | +3.761 | 0.333 | 0.278 | 0.500 |
| L | raw | 0.2124 | 0.0499 | 0.0255 | 0.512 | -0.913 | 0.000 | 0.167 | 0.500 |
| L | centered | 0.0123 | 0.0029 | 0.1654 | 56.735 | -0.490 | 0.667 | 0.222 | 0.667 |
| L | z | n/a | n/a | 1.0000 | n/a | +0.042 | 0.667 | 0.222 | 0.667 |

## st/all-MiniLM-L6-v2

Not run: `sentence-transformers` is not installed in any local interpreter.
