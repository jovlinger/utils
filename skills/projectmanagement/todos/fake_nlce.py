"""Test support: a bag-of-words stand-in for the Apple NLCE embedder.

Production ships exactly one real embedder (``apple``), which needs the macOS
Swift sidecar -- so tests that must rank text hermetically mock the sidecar
instead of selecting a different backend. This module is that mock, in the two
flavors tests need:

* ``install(dir)`` writes an executable fake sidecar speaking the same JSON-lines
  protocol as ``apple_embedder/nlce-embed``, for CLI tests that run ``todo.py``
  as a subprocess (point ``$TODO_APPLE_NLCE_BIN`` at it and use
  ``--embedder apple``).
* ``BowEmbedder`` is the same scoring as an in-process ``Embedder``, for unit
  tests that call scoring helpers directly.

Both score by **bag of words**: md5 of each whitespace token into one of ``DIM``
buckets, counted, then l2-normalized. That gives two properties the search and
tagging tests rely on, which a digest-of-the-whole-string double like
``MockEmbedder`` cannot provide:

1. Vectors are non-negative, so cosine is never negative and shared tokens
   always *raise* similarity.
2. Texts sharing no token score EXACTLY 0.0 -- a hard cutoff, so a test can
   assert an unrelated todo is absent from results rather than merely ranked low.

This is deliberately lexical, and deliberately NOT a production backend: the
retired ``hash`` embedder scored this way, and being lexical is precisely why it
was useless for semantic work (see ``todo_embed._BACKENDS``). It survives here
as a test oracle, where predictability is the point.
"""

from __future__ import annotations

import hashlib
import math
import os
import stat
from pathlib import Path
from typing import List, Sequence

from todo_embed import Embedder

# Bucket count. Small enough to keep fake vectors readable, large enough that the
# handful of distinct tokens in a test never collide.
DIM = 128

# What AppleEmbedder's handshake reports, hence the fingerprint tests see:
# apple_nlce:test-bow:r1:pool=mean:norm=l2:v1
MODEL = "test-bow"
REVISION = 1
FINGERPRINT = f"apple_nlce:{MODEL}:r{REVISION}:pool=mean:norm=l2:v1"


def bag_of_words(text: str, dim: int = DIM) -> List[float]:
    """l2-normalized bag-of-words vector: md5 each token into a bucket, count, normalize."""
    vec = [0.0] * dim
    for token in (part.lower() for part in text.split() if part.strip()):
        bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % dim
        vec[bucket] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return vec if norm == 0.0 else [v / norm for v in vec]


class BowEmbedder(Embedder):
    """In-process bag-of-words embedder for unit tests (see module docstring)."""

    def __init__(self, dim: int = DIM) -> None:
        self._dim = dim

    def fingerprint(self) -> str:
        return FINGERPRINT

    def dimension(self) -> int:
        return self._dim

    def embed(self, text: str) -> List[float]:
        return bag_of_words(text, self._dim)


# The sidecar script. Kept self-contained (no import of this module) because it
# runs as its own process, possibly with a different cwd/sys.path.
_SIDECAR = '''#!/usr/bin/env python3
"""Fake apple_embedder/nlce-embed: bag-of-words vectors over JSON lines."""
import hashlib, json, math, sys

DIM = {dim}

def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\\n")
    sys.stdout.flush()

def vector_for(text):
    vec = [0.0] * DIM
    for token in (p.lower() for p in text.split() if p.strip()):
        vec[int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vec))
    return vec if norm == 0.0 else [v / norm for v in vec]

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    req = json.loads(line)
    op = req.get("op")
    if op == "info":
        emit({{"model": "{model}", "revision": {revision}, "dim": DIM}})
    elif op == "embed":
        emit({{"vector": vector_for(req.get("text", ""))}})
    else:
        emit({{"error": "unknown op"}})
'''


def sidecar_source(dim: int = DIM) -> str:
    """The fake sidecar's Python source."""
    return _SIDECAR.format(dim=dim, model=MODEL, revision=REVISION)


def install(directory: str, name: str = "fake-nlce", dim: int = DIM) -> str:
    """Write the executable fake sidecar into *directory*; return its path.

    Point ``$TODO_APPLE_NLCE_BIN`` at the result and the ``apple`` backend loads
    it instead of the real Swift binary -- an explicit ``bin_path`` bypasses the
    macOS-version gate, so this works on any platform.
    """
    path = Path(directory) / name
    path.write_text(sidecar_source(dim), encoding="utf-8")
    os.chmod(path, os.stat(path).st_mode | stat.S_IEXEC | stat.S_IXGRP)
    return str(path)


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    """Cosine similarity, re-exported so tests need not import todo_embed for it."""
    from todo_embed import cosine_similarity

    return cosine_similarity(a, b)
