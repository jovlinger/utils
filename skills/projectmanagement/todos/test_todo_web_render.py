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
    "todo:d56d/workitem/18 is NOT achievable with the committed corpus.\n\n"
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


BIG = "x" * (todo_web._COLLAPSE_CHARS + 1)


def _top(page: str) -> str:
    """Just the rendered representation -- not the stylesheet or the script,
    which name every class the page can ever use."""
    return page.split('<div id="top">', 1)[1].split('<div id="divider">', 1)[0]


def _section_of(page: str, title: str) -> str:
    """The rendered <section> for *title*, header included."""
    marker = f"<h2>{title}</h2>"
    start = page.rindex("<section", 0, page.index(marker))
    return page[start : page.index("</section>", start)]


class SectionCollapseTest(unittest.TestCase):
    """An oversized section starts collapsed; a small one is untouched."""

    def test_oversized_body_collapses_with_a_line_count(self) -> None:
        body = ("a line of body text\n" * 200)
        page = _page({**_todo({"working": {}}, []), "Body": {"raw": body, "objid": "0001"}})
        section = _section_of(page, "Body")
        self.assertIn("<details class=\"sec\">", section)
        self.assertIn("200 lines", section)
        self.assertNotIn(" open>", section)  # closed on arrival

    def test_small_body_renders_exactly_as_before(self) -> None:
        page = _page({**_todo({"working": {}}, []), "Body": {"raw": "two\nlines", "objid": "0001"}})
        section = _section_of(page, "Body")
        self.assertNotIn("<details", section)
        self.assertNotIn("sec-hint", section)

    def test_many_work_items_collapse_on_count_alone(self) -> None:
        # Twenty one-word boxes wrap into as much screen as one long box, so
        # the item count is its own trigger, independent of text length.
        items = [
            {"kind": "code", "summary": "short", "sha": "a" * 40, "done": True, "objid": f"01{i:02d}"}
            for i in range(todo_web._COLLAPSE_ITEMS + 1)
        ]
        section = _section_of(_page(_todo({"working": {}}, items)), "Work items")
        self.assertIn("<details", section)
        self.assertIn(f"{len(items)} items", section)

    def test_few_work_items_do_not_collapse(self) -> None:
        items = [{"kind": "code", "summary": "short", "sha": "a" * 40, "done": True, "objid": "0101"}]
        section = _section_of(_page(_todo({"working": {}}, items)), "Work items")
        self.assertNotIn("<details", section)

    def test_long_state_note_collapses(self) -> None:
        section = _section_of(_page(_todo({"userneeded": {"note": BIG}}, [])), "State")
        self.assertIn("<details", section)

    def test_singular_hint_reads_as_one_item(self) -> None:
        self.assertEqual("1 item", todo_web._size_hint(1, "items"))
        self.assertEqual("2 items", todo_web._size_hint(2, "items"))

    def test_static_fold_rendition_never_grows_toggles(self) -> None:
        # The fold shows another todo read-only; it is not a page you navigate.
        big = {**_todo({"working": {}}, []), "Body": {"raw": BIG, "objid": "0001"}}
        self.assertNotIn("<details", todo_web._static_repr_html(Path("."), big, ""))


class BoxClampTest(unittest.TestCase):
    """An oversized box summary clamps; the expander does not open the fold."""

    def _item(self, summary: str) -> Dict[str, Any]:
        return {
            "kind": "code",
            "summary": summary,
            "sha": "a" * 40,
            "done": True,
            "objid": "0101",
        }

    def test_paragraph_summary_clamps_with_an_expander(self) -> None:
        para = "y" * (todo_web._CLAMP_CHARS + 1)
        top = _top(_page(_todo({"working": {}}, [self._item(para)])))
        self.assertIn('class="wi-sum clamped"', top)
        self.assertIn('<button class="more" type="button">...more</button>', top)
        self.assertIn(para, top)  # full text stays in the DOM for find and copy

    def test_short_summary_is_untouched(self) -> None:
        top = _top(_page(_todo({"working": {}}, [self._item("a one-line step")])))
        self.assertIn('<div class="wi-sum">a one-line step</div>', top)
        self.assertNotIn("clamped", top)
        self.assertNotIn('class="more"', top)

    def test_expander_stops_propagation_like_an_idlink(self) -> None:
        # Without this the box's own click handler also swaps the fold.
        page = _page(_todo({"working": {}}, [self._item("z" * 300)]))
        handler = page.split("#top .more'")[1].split("});")[0]
        self.assertIn("e.stopPropagation();", handler)

    def test_static_boxes_in_the_fold_stay_plain(self) -> None:
        big = {
            "Id": "13e5" + "0" * 60,
            "Branch": "13e5-child",
            "State": {"done": {}},
            "Summary": {"raw": "child", "objid": "0000"},
            "WorkItems": [self._item("w" * 400)],
        }
        static = todo_web._static_repr_html(Path("."), big, "")
        self.assertNotIn("clamped", static)
        self.assertNotIn('class="more"', static)


class FocusOpensTest(unittest.TestCase):
    """A permalink target is never hidden inside the section that holds it."""

    def _big_todo(self) -> Dict[str, Any]:
        items = [
            {
                "kind": "code",
                "summary": f"step {i} " + "q" * 300,
                "sha": "a" * 40,
                "done": True,
                "objid": f"02{i:02d}",
            }
            for i in range(todo_web._COLLAPSE_ITEMS + 2)
        ]
        return {**_todo({"working": {}}, items), "Body": {"raw": BIG, "objid": "0001"}}

    def render(self, focus: str = "") -> str:
        return todo_web.render_todo_page(Path("."), self._big_todo(), focus_objid=focus)

    def test_section_holding_the_target_renders_open(self) -> None:
        section = _section_of(self.render(focus="0203"), "Work items")
        self.assertIn('<details class="sec" open>', section)
        self.assertIn('data-obj="0203"', section)  # and the target is really in it

    def test_same_section_is_closed_without_focus(self) -> None:
        self.assertIn('<details class="sec">', _section_of(self.render(), "Work items"))

    def test_focus_does_not_open_sibling_sections(self) -> None:
        # "Opens if needed" -- not "opens everything".
        page = self.render(focus="0203")
        self.assertIn('<details class="sec">', _section_of(page, "Body"))

    def test_focus_on_a_section_field_opens_that_section(self) -> None:
        # 0001 is the Body field object, not a box: a section target.
        self.assertIn('<details class="sec" open>', _section_of(self.render(focus="0001"), "Body"))

    def test_rendering_the_same_permalink_twice_is_idempotent(self) -> None:
        self.assertEqual(self.render(focus="0203"), self.render(focus="0203"))

    def test_unknown_focus_opens_nothing(self) -> None:
        page = self.render(focus="ffff")
        self.assertNotIn(" open>", _top(page))

    def test_holds_never_reports_true_without_a_target(self) -> None:
        # The guard that keeps an unfocused page from opening every section.
        self.assertFalse(todo_web._holds({"objid": "0001"}, ""))
        self.assertTrue(todo_web._holds({"objid": "0001"}, "0001"))


class ObjidBadgeTest(unittest.TestCase):
    """Every objid-bearing box/section shows its own objid, small and visible
    (debug/permalink aid), and never in a static fold rendition -- same scope
    as `_box_attrs`."""

    def test_work_item_objid_is_visible(self) -> None:
        item = {"kind": "task", "summary": "step one", "done": False, "objid": "0101"}
        top = _top(_page(_todo({"working": {}}, [item])))
        self.assertIn('<span class="objid-tag mono">0101</span>', top)

    def test_summary_objid_is_visible(self) -> None:
        # _todo() stamps Summary with objid "0000".
        top = _top(_page(_todo({"working": {}}, [])))
        self.assertIn('<span class="objid-tag mono">0000</span>', top)

    def test_body_objid_is_visible(self) -> None:
        page = _page({**_todo({"working": {}}, []), "Body": {"raw": "text", "objid": "0099"}})
        self.assertIn('<span class="objid-tag mono">0099</span>', _top(page))

    def test_subtodo_and_parent_objid_are_visible(self) -> None:
        child_ref = {"Id": "13e5" + "0" * 60, "Branch": "13e5-x", "objid": "0006"}
        todo = {
            **_todo({"working": {}}, []),
            "Subtodos": [child_ref],
            "Parent": [{**child_ref, "objid": "0007"}],
        }
        top = _top(todo_web.render_todo_page(Path("."), todo))
        self.assertIn('<span class="objid-tag mono">0006</span>', top)
        self.assertIn('<span class="objid-tag mono">0007</span>', top)

    def test_meta_row_objid_is_visible(self) -> None:
        todo = {**_todo({"working": {}}, []), "Scope": {"objid": "0009", "path_from_root": "x"}}
        self.assertIn(
            '<span class="objid-tag mono">0009</span>', _section_of(_page(todo), "Fields")
        )

    def test_a_list_shaped_section_carries_no_badge_of_its_own(self) -> None:
        # Work items has no container-level objid -- only its elements do
        # (tested above), so exactly one badge should appear: the item's.
        item = {"kind": "task", "summary": "step one", "done": False, "objid": "0101"}
        section = _section_of(_page(_todo({"working": {}}, [item])), "Work items")
        self.assertEqual(1, section.count("objid-tag"))

    def test_static_fold_rendition_never_shows_a_badge(self) -> None:
        big = {
            "Id": "13e5" + "0" * 60,
            "Branch": "13e5-child",
            "State": {"done": {}},
            "Summary": {"raw": "child", "objid": "0000"},
            "WorkItems": [{"kind": "task", "summary": "x", "done": False, "objid": "0101"}],
        }
        static = todo_web._static_repr_html(Path("."), big, "")
        self.assertNotIn("objid-tag", static)


if __name__ == "__main__":
    unittest.main()
