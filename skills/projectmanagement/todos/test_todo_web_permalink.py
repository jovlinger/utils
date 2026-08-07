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
    ],
    "Subtodos": [{"Id": "13e5" + "0" * 60, "Branch": "13e5-child", "objid": "0006"}],
    "_nextobjid": 7,
}


class PermalinkTargetTest(unittest.TestCase):
    """permalink_target picks the anchor a deep link should land on."""

    def target(self, *segments: str) -> str:
        return todo_web.permalink_target(TODO, list(segments))

    def test_object_path_anchors_on_that_object(self) -> None:
        self.assertEqual(f"/?id={TID}#obj-0003", self.target("workitem", "1"))

    def test_scalar_path_anchors_on_its_enclosing_object(self) -> None:
        self.assertEqual(f"/?id={TID}#obj-0002", self.target("workitem", "0", "summary"))

    def test_objid_form(self) -> None:
        self.assertEqual(f"/?id={TID}#obj-0006", self.target("objid", "0006"))

    def test_sha_where_clause(self) -> None:
        self.assertEqual(f"/?id={TID}#obj-0002", self.target("workitem", "sha", "883368"))

    def test_record_itself_has_no_fragment(self) -> None:
        self.assertEqual(f"/?id={TID}", self.target())

    def test_unstamped_subtree_has_no_fragment(self) -> None:
        # State is deliberately never stamped, so there is no anchor to land on.
        self.assertEqual(f"/?id={TID}", self.target("state", "working", "owner"))

    def test_bad_path_raises(self) -> None:
        with self.assertRaises(todo_url.TodoUrlError):
            self.target("nope")


class PermalinkRouteTest(unittest.TestCase):
    """The running server redirects a permalink onto the anchored page."""

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

    def _get(self, path: str) -> urllib.response.addinfourl:
        """GET *path* WITHOUT following redirects."""

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *_args, **_kwargs):  # noqa: D102
                return None

        opener = urllib.request.build_opener(NoRedirect)
        return opener.open(self.base + path, timeout=10)

    def test_permalink_redirects_to_the_anchored_page(self) -> None:
        try:
            self._get("/557ab9d3/workitem/1")
            self.fail("expected a redirect")
        except urllib.error.HTTPError as exc:
            self.assertEqual(302, exc.code)
            self.assertEqual(f"/?id={TID}#obj-0003", exc.headers["Location"])

    def test_short_selector_and_scalar_path(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/557a/workitem/0/summary")
        self.assertEqual(302, caught.exception.code)
        self.assertEqual(f"/?id={TID}#obj-0002", caught.exception.headers["Location"])

    def test_objid_permalink(self) -> None:
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self._get("/557a/objid/0006")
        self.assertEqual(f"/?id={TID}#obj-0006", caught.exception.headers["Location"])

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

    def test_search_route_is_unchanged(self) -> None:
        self.assertEqual(200, self._get("/search?q=").status)


if __name__ == "__main__":
    unittest.main()
