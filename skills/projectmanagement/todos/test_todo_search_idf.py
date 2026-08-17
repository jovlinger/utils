#!/usr/bin/env python3
"""END test for IDF full-text search (todo:ead99397).

This is the completion gate for the branch, written before any of it exists and
red until the last chunk lands. It is deliberately literate and black-box: it
drives `todo.py` as a binary over a synthetic corpus and walks the MVP flow a
user actually performs, in order.

The story it tells:

  1. A corpus where one word is everywhere and another is nearly unique. Search
     for both at once. Lexical relevance means the todo holding the RARE word
     wins, even though the todo holding only the common word matches a query
     term just as literally. That is the whole point of IDF, and the ranker
     being replaced could not express it -- it scored every term the same.
  2. Morphology: a query in the singular finds the plural, and a bare verb finds
     its gerund. Nothing more clever than that is claimed.
  3. The common word is DISCOVERED to be a stopword -- nobody typed a list -- and
     the discovery is collected into the todo dir's config.json where it can be
     read and edited.
  4. `clear-search-data` drops what search derived (the stopword list and the
     stored vectors). The next search re-derives it and returns the same answer,
     which is what makes the data safe to throw away.
  5. With the embedder turned off in config, search still works. This test proves
     it the hard way: it points the sidecar at a path that does not exist, so any
     attempt to embed would fail loudly rather than silently degrade.

Ranking assertions run with the embedder OFF on purpose. Fusing a vector ranker
in would make "did IDF order these correctly" untestable, and the off switch is
itself part of the deliverable, so the deterministic lane is the honest one.
"""

from __future__ import annotations

import json
import sqlite3
import sys
import unittest
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_todo import TodoCase  # noqa: E402  (shared temp-repo + subprocess harness)

# The corpus-wide word (in every todo below) and the rare one (in exactly one).
COMMON = "widget"
RARE = "quokka"


class SearchIdfEndTest(TodoCase):
    """The branch's acceptance gate. One literate walk through the MVP flow."""

    # ---- helpers -------------------------------------------------------

    def _config(self) -> Dict[str, Any]:
        """The todo dir's config.json, as a dict (it always exists in a test)."""
        return json.loads((self._db_dir / "config.json").read_text(encoding="utf-8"))

    def _write_config(self, **keys: Any) -> None:
        """Merge *keys* into config.json, preserving what the tool put there."""
        config = self._config()
        config.update(keys)
        (self._db_dir / "config.json").write_text(
            json.dumps(config, indent=2) + "\n", encoding="utf-8"
        )

    def _embedding_rows(self) -> List[tuple]:
        """(ticket_id, field_path, embedder) straight from the embeddings index."""
        db = self._db_dir / "sqlite.db"
        if not db.exists():
            return []
        conn = sqlite3.connect(str(db))
        try:
            return conn.execute(
                "SELECT ticket_id, field_path, embedder FROM embeddings"
            ).fetchall()
        finally:
            conn.close()

    def _seed(self, label: str, summary: str, body: str = "") -> str:
        """Create one todo with known text; return its 8-hex short id."""
        tid = self.mint()
        self.write_ticket(f"{tid[:8]}-{label}", tid, summary=summary, body=body)
        return tid[:8]

    def _search(self, *args: str, embedder_bin: str = "") -> str:
        """Run search, assert it succeeded, return stdout (rank order preserved)."""
        env_backup = self._env.get("TODO_APPLE_NLCE_BIN", "")
        if embedder_bin:
            self._env["TODO_APPLE_NLCE_BIN"] = embedder_bin
        try:
            proc = self.todo("search", *args)
        finally:
            self._env["TODO_APPLE_NLCE_BIN"] = env_backup
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def _rank(self, stdout: str, short_id: str) -> int:
        """Position of a todo in the result list; fails the test when absent."""
        self.assertIn(short_id, stdout, f"{short_id} missing from results:\n{stdout}")
        return stdout.index(short_id)

    # ---- the walk ------------------------------------------------------

    def test_end_to_end_idf_search(self) -> None:
        # The embedder is off for the whole walk except where noted, so every
        # ranking assertion below is pure lexical IDF and nothing else.
        self._write_config(embedder=None)

        # 1. A corpus of ten todos. All of them talk about widgets; exactly one
        #    mentions a quokka. Two of them are the ones under test: `rare_id`
        #    matches only the rare term, `common_id` matches only the common one.
        rare_id = self._seed("rare", f"{RARE} sighting log")
        common_id = self._seed("common", f"{COMMON} inventory")
        for n in range(8):
            self._seed(f"filler{n}", f"{COMMON} maintenance pass {n}")

        # Searching for both terms at once, the rare match must win. Under the
        # ranker this replaces, both todos matched exactly one term and scored
        # identically -- there was no signal to separate them.
        both = self._search(COMMON, RARE)
        self.assertEqual(
            0,
            self._rank(both, rare_id),
            f"the rare term must produce the top hit:\n{both}",
        )
        # The common-only match does not outrank it, and in fact does not appear
        # at all: once the corpus-wide word is a discovered stopword, matching
        # only that word is not matching. See step 3 -- and note the query as a
        # WHOLE still has a real term, which is what licenses dropping it here.
        self.assertNotIn(
            common_id, both, f"a stopword-only match should not surface:\n{both}"
        )

        # 2. Morphology, and only the two forms claimed: a plural noun is found
        #    by its singular, and a gerund by its bare verb.
        plural_id = self._seed("plural", "stores embeddings for later recall")
        gerund_id = self._seed("gerund", "merging the child branch back")
        self.assertIn(plural_id, self._search("embedding"))
        self.assertIn(gerund_id, self._search("merge"))

        # ...while a word that merely ends in those letters is not butchered:
        # "class" is not "clas", so a search for it still finds it.
        class_id = self._seed("class", "class hierarchy for the command taxonomy")
        self.assertIn(class_id, self._search("class"))

        # 3. Nobody wrote a stopword list. The common word earns the label by
        #    being everywhere, and the discovery is durable in config.json.
        stopwords = self._config().get("search_stopwords") or []
        self.assertIn(
            COMMON,
            stopwords,
            f"{COMMON!r} is in nearly every todo and should have been discovered "
            f"as a stopword; config.json holds {stopwords!r}",
        )
        self.assertNotIn(
            RARE, stopwords, "a rare term must never be discovered as a stopword"
        )

        # 4. Search data is derived, so it can be thrown away. Re-enable the
        #    embedder for one search so there are vectors to drop as well, and
        #    confirm both kinds of derived data are actually present first.
        self._write_config(embedder="apple")
        self._search(COMMON, RARE, "--embedder", "apple")
        self.assertNotEqual([], self._embedding_rows(), "expected stored vectors")

        cleared = self.todo("clear-search-data", "ALL")
        self.assertEqual(cleared.returncode, 0, cleared.stderr)
        self.assertEqual([], self._embedding_rows(), "vectors survived the clear")
        self.assertFalse(
            self._config().get("search_stopwords"),
            "the discovered stopword list survived the clear",
        )

        # The next search re-derives everything and lands on the same answer --
        # the property that makes clearing safe rather than destructive.
        self._write_config(embedder=None)
        again = self._search(COMMON, RARE)
        self.assertEqual(
            0,
            self._rank(again, rare_id),
            f"ranking must survive a clear + re-derive:\n{again}",
        )
        # ...and re-derivation is a genuine recomputation, not a restore of what
        # was cleared. The corpus grew during step 2, and a word in 9 of 13 todos
        # is no longer common enough to be a stopword the way a word in 9 of 10
        # was. Clearing is therefore also how a stale list gets corrected.
        self.assertNotIn(COMMON, self._config().get("search_stopwords") or [])

        # 5. Finally, the off switch is real and not merely a preference. With
        #    the sidecar binary pointed at a path that does not exist, a search
        #    that tried to embed anything would fail; this one must not.
        missing = str(self._db_dir / "no-such-embedder-binary")
        self.assertFalse(Path(missing).exists())
        off = self._search(RARE, embedder_bin=missing)
        self.assertIn(rare_id, off)
        self.assertEqual([], self._embedding_rows(), "off switch still wrote vectors")


if __name__ == "__main__":
    unittest.main()
