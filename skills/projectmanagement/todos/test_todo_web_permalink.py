#!/usr/bin/env python3
"""Tests for the viewer's permalink route: /<todoid>/<path...> -> anchored page."""

from __future__ import annotations

import contextlib
import io
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import List, Tuple

import todo_url
import todo_web

TID = "557ab9d3" + "0" * 56

TODO = {
    "Id": TID,
    "Branch": "557ab9d3-routing",
    "State": {"working": {"owner": "agent"}},
    "Summary": {"raw": "routing and agent choice", "objid": "0000"},
    "WorkItems": [
        {"summary": "first", "sha": "883368de28aa", "done": True, "objid": "0002"},
        {"summary": "second", "done": False, "objid": "0003"},
        # execution is stamped but never drawn on its own -- the case that
        # proves focus walks outward to the box that contains it.
        {
            "summary": "third",
            "done": False,
            "objid": "0004",
            "execution": {"mode": "parallel", "objid": "0005"},
        },
    ],
    "Subtodos": [{"Id": "13e5" + "0" * 60, "Branch": "13e5-child", "objid": "0006"}],
    "_nextobjid": 7,
}


class ResolveFocusTest(unittest.TestCase):
    """resolve_focus picks the object the page should open focused on."""

    def focus(self, *segments: str) -> str:
        return todo_web.resolve_focus(Path("."), dict(TODO), list(segments))

    def test_object_path_focuses_that_object(self) -> None:
        self.assertEqual("0003", self.focus("workitem", "1"))

    def test_scalar_path_focuses_its_enclosing_object(self) -> None:
        self.assertEqual("0002", self.focus("workitem", "0", "summary"))

    def test_objid_form(self) -> None:
        self.assertEqual("0006", self.focus("objid", "0006"))

    def test_sha_where_clause(self) -> None:
        self.assertEqual("0002", self.focus("workitem", "sha", "883368"))

    def test_undrawn_object_walks_out_to_its_box(self) -> None:
        # WorkItems.2.execution (objid 0005) is nested inside a work item and is
        # not drawn on its own, so focus lands on the work item that holds it.
        self.assertEqual("0004", self.focus("objid", "0005"))
        self.assertEqual("0004", self.focus("workitem", "2", "execution", "mode"))

    def test_section_target(self) -> None:
        self.assertEqual("0000", self.focus("summary", "raw"))

    def test_record_itself_is_unfocused(self) -> None:
        self.assertEqual("", self.focus())

    def test_unstamped_subtree_is_unfocused(self) -> None:
        # State is never stamped, so there is nothing to focus -- but the todo
        # still renders; this is not an error.
        self.assertEqual("", self.focus("state", "working", "owner"))

    def test_bad_path_raises(self) -> None:
        with self.assertRaises(todo_url.TodoUrlError):
            self.focus("nope")


class RenderFocusTest(unittest.TestCase):
    """render_todo_page embeds the objid the page should open focused on.

    The focusing itself is browser JS (focusOn), so what is asserted here is
    the server's half of the contract: the objid it hands the page, and that
    the element that objid names is actually present to focus.
    """

    def render(self, **kwargs: str) -> str:
        return todo_web.render_todo_page(Path("."), dict(TODO), **kwargs)

    def test_focus_objid_is_embedded(self) -> None:
        page = self.render(focus_objid="0003")
        self.assertIn('const FOCUS = "0003";', page)
        self.assertIn('data-obj="0003"', page)

    def test_unfocused_by_default(self) -> None:
        self.assertIn('const FOCUS = "";', self.render())

    def test_section_objid_is_embedded_and_addressable(self) -> None:
        page = self.render(focus_objid="0000")
        self.assertIn('const FOCUS = "0000";', page)
        self.assertIn('data-objs="0000"', page)  # the Summary section


class PermalinkRouteTest(unittest.TestCase):
    """The running server renders a permalink in place, focused, with no redirect."""

    base: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        """Start the viewer on an ephemeral port, reading the URL it prints."""

        def resolver(selector: str) -> Tuple[Path, dict]:
            if not TID.startswith(selector):
                raise todo_web.TodoWebError(f"no todo matches {selector!r}")
            return Path("."), TODO

        def searcher(_query: str) -> List[dict]:
            return []

        printed = io.StringIO()

        def run() -> None:
            with contextlib.redirect_stdout(printed):
                todo_web.serve(
                    Path("."), port=0, resolver=resolver, searcher=searcher
                )

        # Daemon: serve_forever() never returns, and the socket dies with the
        # test process. One server serves every case in this class.
        threading.Thread(target=run, daemon=True).start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if printed.getvalue().strip():
                cls.base = printed.getvalue().strip().rstrip("/")
                return
            time.sleep(0.01)
        raise AssertionError("viewer did not print its URL")

    def _get(self, path: str):
        """GET *path*, following nothing -- a permalink must not redirect."""

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):  # noqa: D102
                return None

        return urllib.request.build_opener(NoRedirect).open(self.base + path, timeout=10)

    def test_permalink_renders_the_focused_page_in_place(self) -> None:
        resp = self._get("/557ab9d3/workitem/1")
        self.assertEqual(200, resp.status)
        page = resp.read().decode("utf-8")
        self.assertIn('const FOCUS = "0003";', page)
        self.assertIn("routing and agent choice", page)  # the WHOLE todo, not a fragment
        self.assertIn('data-obj="0003"', page)

    def test_short_selector_and_scalar_path(self) -> None:
        page = self._get("/557a/workitem/0/summary").read().decode("utf-8")
        self.assertIn('const FOCUS = "0002";', page)

    def test_objid_permalink(self) -> None:
        page = self._get("/557a/objid/0006").read().decode("utf-8")
        self.assertIn('const FOCUS = "0006";', page)

    def test_unfocusable_path_still_renders_the_todo(self) -> None:
        resp = self._get("/557a/state/working/owner")
        self.assertEqual(200, resp.status)
        page = resp.read().decode("utf-8")
        self.assertIn('const FOCUS = "";', page)
        self.assertIn("routing and agent choice", page)

    def test_unresolvable_path_is_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/557a/nope")
        self.assertEqual(404, caught.exception.code)

    def test_unknown_todo_is_404(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/ffffffff/summary")
        self.assertEqual(404, caught.exception.code)

    def test_non_permalink_path_still_404s(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/favicon.ico")
        self.assertEqual(404, caught.exception.code)

    def test_query_form_still_renders(self) -> None:
        resp = self._get("/?id=" + TID)
        self.assertEqual(200, resp.status)
        self.assertIn("routing and agent choice", resp.read().decode("utf-8"))

    def test_search_route_is_unchanged(self) -> None:
        self.assertEqual(200, self._get("/search?q=").status)


if __name__ == "__main__":
    unittest.main()
