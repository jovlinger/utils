"""Lexical search for todos: tokenizing, stemming, IDF, discovered stopwords.

This is the NON-vector half of `todo.py search`. It exists because the lexical
ranker it replaces weighted no term by how common that term is: a whole-term
substring hit scored 1.0 and each present whitespace token added 0.1, so
"todo", "search" and "the" counted exactly as much as a rare distinguishing
term. Fused into the ranking alongside the embedders, a corpus-wide word could
drag an irrelevant todo up the list.

Two design notes worth knowing before editing:

* **The stemmer is a seam, not an algorithm.** ``STEMMER`` is a module-level
  hook; rebind it to drop in a real morphological analyzer (Porter, Snowball,
  spaCy) without touching a single caller. The shipped ``stem`` is deliberately
  crude -- de-pluralize, de-gerund, and nothing else -- because the point of
  this pass is the seam.
* **Nothing here is persisted per todo.** The corpus is tokenized fresh on each
  search, which for a few hundred records is milliseconds. Embedding is
  expensive and earns storage; tokenizing does not. The one durable artifact is
  the DISCOVERED stopword list, which lives in the todo dir's config.json
  because a human should be able to read and edit it.
"""

from __future__ import annotations

import math
import re
from typing import Callable, Dict, Iterable, List, Mapping, Sequence, Set

# A token is a run of letters/digits; everything else is a separator. Keeping
# digits matters -- ticket keys and ids ("bh 791", "ead99397") are exactly what
# people type into search.
_TOKEN_RE = re.compile(r"[0-9a-z]+")

# Sibilants that take an "-es" plural ("boxes", "batches"). A word ending in
# "-es" without one of these is a plain "-s" plural of a word ending in "e"
# ("notes"), and stripping "es" there would produce a different word ("not").
_SIBILANTS = ("s", "x", "z", "ch", "sh")

# Refuse to de-gerund into a stub: "thing" -> "th" is not a stem, it is damage.
_MIN_STEM_AFTER_ING = 4

# Only drop a trailing "e" from a reasonably long word. This is what makes
# "merge" and "merging" agree (both -> "merg") without turning "note" into
# "not" or "code" into "cod".
_MIN_LEN_FOR_FINAL_E = 5

#: A stemmer maps one already-downcased token to its index form.
Stemmer = Callable[[str], str]


def stem(token: str) -> str:
    """Reduce *token* to its index form: de-pluralized, de-gerunded, else as-is.

    Deliberately minimal, and deliberately IDEMPOTENT -- feeding a stem back in
    must return it unchanged, or the corpus and the query could disagree
    depending on how many times normalization happened to run.

    The rules, in order:

    1. plural: "-es" after a sibilant, else a bare "-s" (never after "ss")
    2. gerund: "-ing", when what remains is still a word-sized stem
    3. a trailing "e" on a long enough word, which is what lets a bare verb
       meet its own gerund ("merge" and "merging" both land on "merg")
    """
    word = token
    if word.endswith("ss"):
        pass  # "class", "pass" -- the word is its own stem
    elif word.endswith("es") and word[:-2].endswith(_SIBILANTS):
        word = word[:-2]
    elif word.endswith("s") and len(word) > 2:
        word = word[:-1]

    if word.endswith("ing") and len(word) - 3 >= _MIN_STEM_AFTER_ING:
        word = word[:-3]

    if word.endswith("e") and len(word) >= _MIN_LEN_FOR_FINAL_E:
        word = word[:-1]

    return word


#: The stemming seam. Rebind this (module attribute) to swap in a real stemmer;
#: every caller reads it at call time, so nothing else changes.
STEMMER: Stemmer = stem


def tokenize(text: str) -> List[str]:
    """Split *text* into stemmed index terms, in order, duplicates kept."""
    return [STEMMER(match.group(0)) for match in _TOKEN_RE.finditer(text.lower())]


def document_frequencies(documents: Iterable[Iterable[str]]) -> Dict[str, int]:
    """Count how many documents each term appears in (presence, not frequency)."""
    frequencies: Dict[str, int] = {}
    for tokens in documents:
        for term in set(tokens):
            frequencies[term] = frequencies.get(term, 0) + 1
    return frequencies


def inverse_document_frequency(document_count: int, frequency: int) -> float:
    """Smoothed IDF: ``ln((N + 1) / (df + 1))``, never negative.

    The +1 smoothing keeps a term present in every document at a small positive
    weight instead of exactly zero, so a query made entirely of common words
    still ranks something rather than collapsing to no signal at all.
    """
    if document_count <= 0:
        return 0.0
    return math.log((document_count + 1.0) / (min(frequency, document_count) + 1.0))


def discover_stopwords(
    frequencies: Mapping[str, int], document_count: int, min_idf: float
) -> List[str]:
    """Terms whose IDF falls below *min_idf* -- this corpus's own stopwords.

    Nobody writes this list. A word earns the label by being everywhere, which
    is why it catches the domain words a shipped English list never would
    ("todo", "sha", "branch", "commit") and leaves alone a rare word that
    happens to be short.
    """
    if document_count <= 0:
        return []
    return sorted(
        term
        for term, frequency in frequencies.items()
        if inverse_document_frequency(document_count, frequency) < min_idf
    )


def score_documents(
    query_terms: Sequence[str],
    documents: Mapping[str, Sequence[str]],
    *,
    stopwords: Set[str] = frozenset(),
) -> Dict[str, float]:
    """Rank *documents* (id -> tokens) against *query_terms* by summed IDF.

    A document scores the IDF of each distinct query term it contains, so a rare
    term dominates and a near-universal one barely registers. Documents matching
    nothing are omitted entirely rather than scored 0, which keeps the hard
    "unrelated todos are absent" cutoff the vector path also has.

    *stopwords* are skipped -- UNLESS every query term is one, in which case
    they are all kept: a search for common words should return the todos holding
    them, not nothing at all.
    """
    if not query_terms or not documents:
        return {}

    frequencies = document_frequencies(documents.values())
    document_count = len(documents)

    wanted = [term for term in query_terms if term not in stopwords]
    if not wanted:
        wanted = list(query_terms)

    weights = {
        term: inverse_document_frequency(document_count, frequencies.get(term, 0))
        for term in dict.fromkeys(wanted)
    }

    scores: Dict[str, float] = {}
    for doc_id, tokens in documents.items():
        present = set(tokens)
        score = sum(weight for term, weight in weights.items() if term in present)
        if score > 0.0:
            scores[doc_id] = score
    return scores
