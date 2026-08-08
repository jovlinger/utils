#!/usr/bin/env python3
"""Tests for what the viewer PUTS ON THE PAGE: the State section, and work
items that carry no commit (blocked, checkpoint).

Both exist because a reader could previously look at a stuck todo and learn
nothing from it: State rendered as the bare word "userneeded" next to the Id
with its note nowhere, and a no-commit item's stored message was never read
(the fold asked git, which has no commit to answer with)."""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path
from typing import Any, Dict

import todo_web

TID = "d56d5d65" + "0" * 56

NOTE = (
    "WI[18] is NOT achievable with the committed corpus.\n\n"
    "MIXED-22: the 18 checklist ids in the burst match none of the 2 recorded.\n\n"
    "DECISION NEEDED: (a) descope, (b) wait for a tenant, (c) move to layer 3."
)

LONG_FORM = (
    "Tried the replay harness against both fixtures.\n\n"
    "It raises InterchangeNotRecorded rather than inventing an answer, which is\n"
    "correct -- so this is a data gap, not a test-authoring problem."
)


def _todo(state: Dict[str, Any], items: list) -> Dict[str, Any]:
    return {
        "Id": TID,
        "Branch": "d56d5d65-debounce",
        "State": state,
        "Summary": {"raw": "debounce CreditLens webhooks", "objid": "0000"},
        "WorkItems": items,
        "_nextobjid": 20,
    }


def _page(todo: Dict[str, Any]) -> str:
    return todo_web.render_todo_page(Path("."), dict(todo))


def _fold_entry(page: str, objid: str) -> Dict[str, Any]:
    """The embedded fold object for *objid* -- what a click would show."""
    match = re.search(r"const DATA = (\{.*?\});", page, re.S)
    assert match, "page carries no embedded DATA"
    raw = match.group(1).replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")
    return json.loads(raw)["objects"][objid]


class StateSectionTest(unittest.TestCase):
    """The State subtree is rendered, metadata included."""

    def test_note_is_on_the_page(self) -> None:
        page = _page(_todo({"userneeded": {"note": NOTE}}, []))
        self.assertIn("<h2>State</h2>", page)
        self.assertIn("userneeded", page)
        self.assertIn("DECISION NEEDED", page)  # the part that was invisible
        self.assertIn("MIXED-22", page)

    def test_multiline_note_keeps_its_paragraphs(self) -> None:
        page = _page(_todo({"userneeded": {"note": NOTE}}, []))
        section = page.split("<h2>State</h2>", 1)[1].split("</section>", 1)[0]
        self.assertIn('<pre class="val body">', section)  # prose, not a one-liner div

    def test_state_without_metadata_still_renders_the_section(self) -> None:
        # Uniformity: a section that appears only sometimes is one a reader
        # learns not to look for.
        page = _page(_todo({"working": {}}, []))
        self.assertIn("<h2>State</h2>", page)
        self.assertIn("working", page)

    def test_disposition_metadata_renders(self) -> None:
        page = _page(_todo({"merged": {"pr": 22660, "merged_into": "dev"}}, []))
        section = page.split("<h2>State</h2>", 1)[1].split("</section>", 1)[0]
        self.assertIn("22660", section)
        self.assertIn("dev", section)

    def test_state_is_not_also_dumped_by_the_generic_fields_section(self) -> None:
        page = _page(_todo({"userneeded": {"note": NOTE}}, []))
        self.assertEqual(1, page.count("<h2>State</h2>"))
        self.assertNotIn('"userneeded"', page)  # no raw json rendition


class BlockedWorkItemTest(unittest.TestCase):
    """A blocked item carries the null sha: no commit, and none is coming."""

    def item(self) -> Dict[str, Any]:
        return {
            "kind": "code",
            "summary": "replay the 22-event burst",
            "sha": "0" * 40,
            "message": LONG_FORM,
            "done": True,
            "objid": "001b",
        }

    def test_sentinel_is_never_rendered_as_a_sha(self) -> None:
        page = _page(_todo({"userneeded": {"note": NOTE}}, [self.item()]))
        self.assertNotIn("sha:00000000", page)
        self.assertIn('<div class="wi-blocked">blocked</div>', page)

    def test_long_form_reaches_the_fold_without_asking_git(self) -> None:
        page = _page(_todo({"userneeded": {"note": NOTE}}, [self.item()]))
        entry = _fold_entry(page, "001b")
        self.assertIn("InterchangeNotRecorded", entry["message"])
        self.assertEqual("", entry["diff"])
        self.assertEqual("", entry["github"])  # the sentinel names no commit to link
        self.assertEqual("", entry["short"])

    def test_checkpoint_message_also_reaches_the_fold(self) -> None:
        # Same code path: no sha means the stored message is all there is.
        item = {
            "kind": "checkpoint",
            "summary": "recon",
            "at_sha": "883368de28",
            "message": "read the routing table; findings in Body",
            "done": True,
            "objid": "001c",
        }
        page = _page(_todo({"working": {}}, [item]))
        self.assertEqual(
            "read the routing table; findings in Body", _fold_entry(page, "001c")["message"]
        )

    def test_a_real_sha_still_resolves_through_git(self) -> None:
        item = {
            "kind": "code",
            "summary": "real work",
            "sha": "883368de28aa",
            "message": "stored copy",
            "done": True,
            "objid": "001d",
        }
        page = _page(_todo({"working": {}}, [item]))
        self.assertIn("sha:883368de", page)
        # git is the source of truth when a commit exists (unavailable here,
        # which is itself proof the stored copy was not substituted).
        self.assertNotIn("stored copy", _fold_entry(page, "001d")["message"])


if __name__ == "__main__":
    unittest.main()
