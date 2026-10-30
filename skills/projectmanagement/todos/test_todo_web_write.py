#!/usr/bin/env python3
"""Tests for the viewer's write endpoint: POST /update under `todo.py web --write`.

Three layers: the request checks and status mapping (handle_update against a
fake updater), the running server in both modes, and the real updater in
todo.py against a real store, which is where the stale-page token and the
single-lock compare-and-write live.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

import test_todo
import todo
import todo_store
import todo_web

PORT = 8765
ORIGIN = f"http://localhost:{PORT}"
GOOD_HEADERS = {
    "Host": f"localhost:{PORT}",
    "Origin": ORIGIN,
    "Content-Type": "application/json",
}
REQUEST = {"id": "ab" * 32, "op": "set-body", "target": "", "value": "new", "token": "t0"}


class FakeUpdater:
    """Records requests; answers with a canned result or raises a canned error."""

    def __init__(self, result: Optional[Dict[str, Any]] = None, error: Optional[Exception] = None):
        self.result = result if result is not None else {"token": "t1"}
        self.error = error
        self.requests: List[Dict[str, Any]] = []

    def token(self, todo_record: Dict[str, Any]) -> str:
        return "t0:" + str(todo_record.get("Id", ""))

    def update(self, request: Dict[str, Any]) -> Dict[str, Any]:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result


def _handle(
    updater: FakeUpdater,
    *,
    headers: Optional[Dict[str, str]] = None,
    body: Optional[bytes] = None,
    port: int = PORT,
) -> Tuple[int, Dict[str, Any]]:
    sent = dict(GOOD_HEADERS if headers is None else headers)
    raw = json.dumps(REQUEST).encode("utf-8") if body is None else body
    return todo_web.handle_update(sent, raw, port, updater)


def _without(key: str) -> Dict[str, str]:
    return {k: v for k, v in GOOD_HEADERS.items() if k != key}


class HandleUpdateTest(unittest.TestCase):
    """Status mapping: 200 applied, 409 stale page, 4xx/503 CLI refusal."""

    def test_success_passes_the_request_to_the_updater(self) -> None:
        updater = FakeUpdater(result={"token": "t9"})
        status, payload = _handle(updater)
        self.assertEqual(200, status)
        self.assertEqual({"token": "t9"}, payload)
        self.assertEqual([REQUEST], updater.requests)

    def test_stale_token_is_409_with_the_stored_value_and_its_token(self) -> None:
        updater = FakeUpdater(
            error=todo_web.UpdateConflict("page is stale", current="cli text", token="t5")
        )
        status, payload = _handle(updater)
        self.assertEqual(409, status)
        self.assertEqual("cli text", payload["current"])
        self.assertEqual("t5", payload["token"])
        self.assertEqual("page is stale", payload["error"])

    def test_cli_refusal_carries_the_command_text(self) -> None:
        updater = FakeUpdater(error=todo_web.UpdateRefused("no todo found for id 'abab'"))
        status, payload = _handle(updater)
        self.assertEqual(400, status)
        self.assertEqual("no todo found for id 'abab'", payload["error"])

    def test_refusal_keeps_its_own_status(self) -> None:
        updater = FakeUpdater(error=todo_web.UpdateRefused("ERETRY: busy", status=503))
        status, payload = _handle(updater)
        self.assertEqual(503, status)
        self.assertEqual("ERETRY: busy", payload["error"])

    def test_json_that_is_not_an_object_is_400(self) -> None:
        updater = FakeUpdater()
        status, _payload = _handle(updater, body=b"[1, 2]")
        self.assertEqual(400, status)
        self.assertEqual([], updater.requests)

    def test_every_loopback_name_is_accepted_with_its_own_origin(self) -> None:
        for host in ("localhost", "127.0.0.1", "[::1]", "LOCALHOST"):
            with self.subTest(host=host):
                headers = {
                    **GOOD_HEADERS,
                    "Host": f"{host}:{PORT}",
                    "Origin": f"http://{host}:{PORT}",
                }
                status, _payload = _handle(FakeUpdater(), headers=headers)
                self.assertEqual(200, status)

    def test_content_type_parameters_are_allowed(self) -> None:
        headers = {**GOOD_HEADERS, "Content-Type": "application/json; charset=utf-8"}
        status, _payload = _handle(FakeUpdater(), headers=headers)
        self.assertEqual(200, status)


class RejectedRequestTest(unittest.TestCase):
    """Each Host / Origin / content-type check refuses with 403 before the updater runs."""

    def assert_refused(self, **kwargs: Any) -> None:
        updater = FakeUpdater()
        status, payload = _handle(updater, **kwargs)
        self.assertEqual(403, status)
        self.assertTrue(payload["error"])
        self.assertEqual([], updater.requests)

    def test_non_loopback_host(self) -> None:
        self.assert_refused(
            headers={
                **GOOD_HEADERS,
                "Host": f"evil.example:{PORT}",
                "Origin": f"http://evil.example:{PORT}",
            }
        )

    def test_lan_address_host(self) -> None:
        self.assert_refused(
            headers={
                **GOOD_HEADERS,
                "Host": f"192.168.1.5:{PORT}",
                "Origin": f"http://192.168.1.5:{PORT}",
            }
        )

    def test_loopback_host_on_another_port(self) -> None:
        self.assert_refused(
            headers={**GOOD_HEADERS, "Host": "localhost:9999", "Origin": "http://localhost:9999"}
        )

    def test_host_without_port(self) -> None:
        self.assert_refused(
            headers={**GOOD_HEADERS, "Host": "localhost", "Origin": "http://localhost"}
        )

    def test_missing_host(self) -> None:
        self.assert_refused(headers=_without("Host"))

    def test_missing_origin(self) -> None:
        self.assert_refused(headers=_without("Origin"))

    def test_foreign_origin(self) -> None:
        self.assert_refused(headers={**GOOD_HEADERS, "Origin": "https://evil.example"})

    def test_origin_of_another_loopback_name(self) -> None:
        self.assert_refused(headers={**GOOD_HEADERS, "Origin": f"http://127.0.0.1:{PORT}"})

    def test_https_origin(self) -> None:
        self.assert_refused(headers={**GOOD_HEADERS, "Origin": f"https://localhost:{PORT}"})

    def test_null_origin(self) -> None:
        self.assert_refused(headers={**GOOD_HEADERS, "Origin": "null"})

    def test_form_content_type(self) -> None:
        self.assert_refused(
            headers={**GOOD_HEADERS, "Content-Type": "application/x-www-form-urlencoded"}
        )

    def test_text_plain_content_type(self) -> None:
        self.assert_refused(headers={**GOOD_HEADERS, "Content-Type": "text/plain"})

    def test_missing_content_type(self) -> None:
        self.assert_refused(headers=_without("Content-Type"))

    def test_body_that_is_not_json(self) -> None:
        self.assert_refused(body=b"op=set-body&value=x")


def _start_server(*, write: bool, updater: Optional[FakeUpdater]) -> str:
    """Start a viewer on an ephemeral loopback port; return its base URL."""
    printed = io.StringIO()

    def run() -> None:
        with contextlib.redirect_stdout(printed):
            todo_web.serve(
                Path("."),
                host="127.0.0.1",
                port=0,
                resolver=mock.Mock(),
                searcher=lambda _q: [],
                write=write,
                updater=updater,
            )

    # Daemon: serve_forever() never returns; the socket dies with the process.
    threading.Thread(target=run, daemon=True).start()
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if printed.getvalue().strip():
            return printed.getvalue().strip().rstrip("/")
        time.sleep(0.01)
    raise AssertionError("viewer did not print its URL")


def _post(base: str, path: str, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
    """POST JSON as a same-origin page would; return (status, decoded body)."""
    req = urllib.request.Request(
        base + path,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json", "Origin": base},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        try:
            return exc.code, json.loads(body)
        except json.JSONDecodeError:
            return exc.code, {"error": body}


class WriteServerTest(unittest.TestCase):
    """The running server under --write routes POST /update through handle_update."""

    updater: FakeUpdater
    base: str = ""

    @classmethod
    def setUpClass(cls) -> None:
        cls.updater = FakeUpdater(result={"token": "t2"})
        cls.base = _start_server(write=True, updater=cls.updater)

    def setUp(self) -> None:
        self.updater.requests.clear()

    def test_update_is_applied(self) -> None:
        status, payload = _post(self.base, "/update", REQUEST)
        self.assertEqual(200, status)
        self.assertEqual({"token": "t2"}, payload)
        self.assertEqual([REQUEST], self.updater.requests)

    def test_other_post_paths_are_404(self) -> None:
        status, _payload = _post(self.base, "/search", REQUEST)
        self.assertEqual(404, status)
        self.assertEqual([], self.updater.requests)

    def test_foreign_origin_is_403_over_the_wire(self) -> None:
        req = urllib.request.Request(
            self.base + "/update",
            data=json.dumps(REQUEST).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", "Origin": "https://evil.example"},
        )
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(req, timeout=10)
        self.assertEqual(403, caught.exception.code)
        self.assertEqual([], self.updater.requests)


class ReadOnlyServerTest(unittest.TestCase):
    """Without --write every POST is answered with an error and nothing is updated."""

    def test_post_update_is_refused(self) -> None:
        updater = FakeUpdater()
        base = _start_server(write=False, updater=updater)
        for path in ("/update", "/", "/abab"):
            with self.subTest(path=path):
                status, _payload = _post(base, path, REQUEST)
                self.assertGreaterEqual(status, 400)
        self.assertEqual([], updater.requests)

    def test_write_without_an_updater_is_refused_at_start(self) -> None:
        with self.assertRaises(todo_web.TodoWebError):
            todo_web.serve(
                Path("."),
                host="127.0.0.1",
                port=0,
                resolver=mock.Mock(),
                searcher=mock.Mock(),
                write=True,
            )


PAGE_TID = "5e" * 32
PAGE_TODO: Dict[str, Any] = {
    "Id": PAGE_TID,
    "Branch": "5e5e5e5e-page",
    "State": {"working": {"owner": "agent"}},
    "Summary": {"raw": "page summary", "objid": "0000"},
    "Body": {"raw": "page body", "objid": "0001"},
    "Tag": [{"raw": "web", "manual": True, "objid": "0002"}],
    "Scope": {"branch": "5e5e5e5e-page", "git_url": "https://example.invalid/r.git"},
    "create_dt": "2026-10-30T00:00:00Z",
    "update_dt": "2026-10-30T00:00:01Z",
    "_nextobjid": 3,
}
FIELD_EDITS = {"set-summary", "set-body", "set-long-summary", "set-ac", "set-actual-summary"}


def render(todo_record: Dict[str, Any], **kwargs: Any) -> str:
    return todo_web.render_todo_page(Path("."), json.loads(json.dumps(todo_record)), **kwargs)


def page_data(page: str) -> Dict[str, Any]:
    """The page's embedded DATA object."""
    match = re.search(r"const DATA = (\{.*?\});\n", page, re.S)
    assert match, "page carries no embedded DATA"
    raw = match.group(1).replace("\\u003c", "<").replace("\\u003e", ">").replace("\\u0026", "&")
    return json.loads(raw)


def edit_keys(page: str) -> List[str]:
    """Every data-edit key rendered on the page, in page order."""
    return re.findall(r'class="edit-toggle" data-edit="([^"]+)"', page)


def meta_row(page: str, key: str) -> str:
    """The rendered Fields row for top-level field *key*."""
    match = re.search(
        r'<div class="meta-row"[^>]*><h3 class="meta-key">'
        + re.escape(key)
        + r"</h3>.*?</div></div>",
        page,
        re.S,
    )
    assert match, f"no Fields row for {key}"
    return match.group(0)


class FieldEditRenderTest(unittest.TestCase):
    """Edit controls on Summary/Body/AC/LongSummary/ActualSummary, only under --write."""

    def test_read_only_page_has_no_edit_controls_and_no_write_data(self) -> None:
        page = render(PAGE_TODO)
        self.assertEqual([], edit_keys(page))
        self.assertNotIn("write", page_data(page))

    def test_write_page_has_one_control_per_text_field(self) -> None:
        page = render(PAGE_TODO, write=True, token="tok")
        keys = edit_keys(page)
        self.assertEqual(sorted(FIELD_EDITS), sorted(keys))
        self.assertEqual(len(keys), len(set(keys)))

    def test_write_page_embeds_the_token_and_each_request(self) -> None:
        data = page_data(render(PAGE_TODO, write=True, token="tok"))
        self.assertEqual("tok", data["write"]["token"])
        edits = data["write"]["edits"]
        self.assertEqual(FIELD_EDITS, set(edits))
        self.assertEqual(
            {"op": "set-body", "target": "", "value": "page body", "label": "Body"},
            edits["set-body"],
        )
        self.assertEqual("page summary", edits["set-summary"]["value"])
        self.assertEqual("", edits["set-ac"]["value"])

    def test_empty_editable_fields_get_a_place_to_be_edited(self) -> None:
        page = render(PAGE_TODO, write=True, token="tok")
        self.assertIn("<h2>Long summary</h2>", page)
        self.assertIn('data-edit="set-ac"', meta_row(page, "AC"))
        self.assertIn('data-edit="set-actual-summary"', meta_row(page, "ActualSummary"))

    def test_read_only_page_does_not_grow_empty_rows(self) -> None:
        page = render(PAGE_TODO)
        self.assertNotIn("<h2>Long summary</h2>", page)
        self.assertNotIn('<h3 class="meta-key">AC</h3>', page)
        self.assertNotIn('<h3 class="meta-key">ActualSummary</h3>', page)

    def test_stored_ac_and_actual_summary_carry_their_controls(self) -> None:
        record = {**PAGE_TODO, "AC": "done when x", "ActualSummary": "it went fine"}
        page = render(record, write=True, token="tok")
        self.assertIn("done when x", meta_row(page, "AC"))
        self.assertIn('data-edit="set-ac"', meta_row(page, "AC"))
        self.assertIn('data-edit="set-actual-summary"', meta_row(page, "ActualSummary"))

    def test_no_control_on_identity_state_tag_scope_or_timestamps(self) -> None:
        page = render(PAGE_TODO, write=True, token="tok")
        for key in ("Branch", "Scope", "Tag", "create_dt", "update_dt"):
            with self.subTest(field=key):
                self.assertNotIn("edit-toggle", meta_row(page, key))
        id_section = re.search(r"<section class=\"part\"><h2>Id</h2>.*?</section>", page, re.S)
        self.assertNotIn("edit-toggle", id_section.group(0))
        state = re.search(r"<h2>State</h2>.*?</section>", page, re.S)
        self.assertNotIn("edit-toggle", state.group(0))

    def test_a_subtodo_rendition_in_the_fold_has_no_controls(self) -> None:
        record = {
            **PAGE_TODO,
            "Subtodos": [{"Id": "13e5" + "0" * 60, "Branch": "13e5-child", "objid": "0003"}],
            "_nextobjid": 4,
        }
        entry = page_data(render(record, write=True, token="tok"))["objects"]["0003"]
        self.assertNotIn("edit-toggle", entry["html"])


LIST_TODO: Dict[str, Any] = {
    **PAGE_TODO,
    "Notes": [{"raw": "first note", "objid": "0003"}, {"raw": "second note", "objid": "0004"}],
    "WorkItems": [
        {"summary": "landed", "done": True, "kind": "code", "sha": "a" * 40, "objid": "0005"},
        {"summary": "parked", "done": True, "kind": "blocked", "message": "m", "objid": "0006"},
        {"summary": "open one", "done": False, "kind": "task", "objid": "0007"},
        {"summary": "open two", "done": False, "kind": "task", "objid": "0008"},
    ],
    "_nextobjid": 9,
}


def tile(page: str, objid: str) -> str:
    """The rendered tile for *objid*, up to the next tile."""
    start = r'<div class="wi[ "][^>]*id="obj-'
    match = re.search(start + objid + r'".*?(?=' + start + r"|</section>)", page, re.S)
    assert match, f"no tile for objid {objid}"
    return match.group(0)


class ListEditRenderTest(unittest.TestCase):
    """Edit on each note and each not-done work item, never on the done prefix."""

    def test_read_only_tiles_have_no_controls(self) -> None:
        page = render(LIST_TODO)
        for objid in ("0003", "0004", "0005", "0006", "0007", "0008"):
            with self.subTest(objid=objid):
                self.assertNotIn("edit-toggle", tile(page, objid))

    def test_every_note_tile_has_its_edit(self) -> None:
        page = render(LIST_TODO, write=True, token="tok")
        for objid in ("0003", "0004"):
            with self.subTest(objid=objid):
                self.assertIn(f'data-edit="note-replace:{objid}"', tile(page, objid))

    def test_not_done_items_have_an_edit_and_done_items_none(self) -> None:
        page = render(LIST_TODO, write=True, token="tok")
        for objid in ("0007", "0008"):
            with self.subTest(objid=objid, done=False):
                self.assertIn(f'data-edit="work-item-replace:{objid}"', tile(page, objid))
        for objid in ("0005", "0006"):
            with self.subTest(objid=objid, done=True):
                self.assertNotIn("edit-toggle", tile(page, objid))

    def test_each_control_sends_its_own_command_and_target(self) -> None:
        edits = page_data(render(LIST_TODO, write=True, token="tok"))["write"]["edits"]
        self.assertEqual(
            {
                "op": "note-replace",
                "target": "objid:0004",
                "value": "second note",
                "label": "note objid:0004",
            },
            edits["note-replace:0004"],
        )
        self.assertEqual(
            {
                "op": "work-item-replace",
                "target": "objid:0007",
                "value": "open one",
                "label": "work item objid:0007",
            },
            edits["work-item-replace:0007"],
        )
        self.assertNotIn("work-item-replace:0005", edits)
        self.assertNotIn("work-item-replace:0006", edits)

    def test_no_control_adds_or_removes_anything(self) -> None:
        edits = page_data(render(LIST_TODO, write=True, token="tok"))["write"]["edits"]
        ops = {spec["op"] for spec in edits.values()}
        self.assertEqual(
            FIELD_EDITS | {"note-replace", "work-item-replace"}, ops - {"work-item-reorder"}
        )


MOVE_TODO: Dict[str, Any] = {
    **LIST_TODO,
    "WorkItems": [
        *LIST_TODO["WorkItems"],
        {"summary": "open three", "done": False, "kind": "task", "objid": "0009"},
    ],
    "_nextobjid": 10,
}


def move_keys(page: str) -> List[str]:
    return re.findall(r'class="move-btn" data-move="([^"]+)"', page)


class MoveRenderTest(unittest.TestCase):
    """Move-up / move-down on not-done work items only, never out of the frontier."""

    def test_read_only_page_has_no_moves(self) -> None:
        self.assertEqual([], move_keys(render(MOVE_TODO)))

    def test_moves_stay_inside_the_not_done_frontier(self) -> None:
        page = render(MOVE_TODO, write=True, token="tok")
        self.assertEqual(
            {
                "work-item-reorder:0007:down",
                "work-item-reorder:0008:up",
                "work-item-reorder:0008:down",
                "work-item-reorder:0009:up",
            },
            set(move_keys(page)),
        )
        for objid in ("0005", "0006"):
            with self.subTest(done=objid):
                self.assertNotIn("move-btn", tile(page, objid))

    def test_each_move_names_its_item_and_destination_index(self) -> None:
        edits = page_data(render(MOVE_TODO, write=True, token="tok"))["write"]["edits"]
        self.assertEqual(
            {
                "op": "work-item-reorder",
                "target": "objid:0008",
                "value": "2",
                "label": "move work item objid:0008 up",
            },
            edits["work-item-reorder:0008:up"],
        )
        self.assertEqual("4", edits["work-item-reorder:0008:down"]["value"])
        self.assertEqual("3", edits["work-item-reorder:0007:down"]["value"])

    def test_a_lone_open_item_has_no_moves(self) -> None:
        record = {**LIST_TODO, "WorkItems": LIST_TODO["WorkItems"][:3]}
        self.assertEqual([], move_keys(render(record, write=True, token="tok")))


class EditPageServeTest(unittest.TestCase):
    """The running server renders edit controls and the token only under --write."""

    def _page(self, *, write: bool) -> str:
        updater = FakeUpdater()

        def resolver(_selector: str) -> Tuple[Path, Dict[str, Any]]:
            return Path("."), json.loads(json.dumps(PAGE_TODO))

        printed = io.StringIO()

        def run() -> None:
            with contextlib.redirect_stdout(printed):
                todo_web.serve(
                    Path("."),
                    host="127.0.0.1",
                    port=0,
                    resolver=resolver,
                    searcher=lambda _q: [],
                    write=write,
                    updater=updater if write else None,
                )

        threading.Thread(target=run, daemon=True).start()
        deadline = time.monotonic() + 10
        while not printed.getvalue().strip() and time.monotonic() < deadline:
            time.sleep(0.01)
        base = printed.getvalue().strip().rstrip("/")
        with urllib.request.urlopen(f"{base}/{PAGE_TID[:8]}", timeout=10) as resp:
            return resp.read().decode("utf-8")

    def test_write_server_pages_carry_controls_and_the_updater_token(self) -> None:
        page = self._page(write=True)
        self.assertEqual(sorted(FIELD_EDITS), sorted(edit_keys(page)))
        self.assertEqual("t0:" + PAGE_TID, page_data(page)["write"]["token"])

    def test_read_only_server_pages_carry_neither(self) -> None:
        page = self._page(write=False)
        self.assertEqual([], edit_keys(page))
        self.assertNotIn("write", page_data(page))


class RecordFingerprintTest(unittest.TestCase):
    """The stale-page token: canonical JSON, stamped embedding vectors ignored."""

    RECORD = {
        "Id": "cd" * 32,
        "Branch": "cdcdcdcd-x",
        "Summary": {"raw": "s", "objid": "0001"},
        "Body": {"raw": "b", "objid": "0002"},
        "update_dt": "2026-10-30T00:00:00Z",
    }

    def test_key_order_does_not_matter(self) -> None:
        reordered = dict(reversed(list(self.RECORD.items())))
        self.assertEqual(todo.record_fingerprint(self.RECORD), todo.record_fingerprint(reordered))

    def test_any_content_change_changes_it(self) -> None:
        changed = json.loads(json.dumps(self.RECORD))
        changed["Body"]["raw"] = "b2"
        self.assertNotEqual(todo.record_fingerprint(self.RECORD), todo.record_fingerprint(changed))

    def test_a_same_second_rewrite_still_changes_it(self) -> None:
        # update_dt has one-second resolution; the token must not lean on it.
        changed = json.loads(json.dumps(self.RECORD))
        changed["Summary"]["raw"] = "s2"
        self.assertEqual(self.RECORD["update_dt"], changed["update_dt"])
        self.assertNotEqual(todo.record_fingerprint(self.RECORD), todo.record_fingerprint(changed))

    def test_stamped_vectors_are_ignored(self) -> None:
        stamped = json.loads(json.dumps(self.RECORD))
        stamped["Body"]["bow-v1"] = [[0.1, 0.2, 0.3]]
        stamped["Summary"]["bow-v1"] = [[0.3, 0.4, 0.5], [0.6, 0.7, 0.8]]
        self.assertEqual(todo.record_fingerprint(self.RECORD), todo.record_fingerprint(stamped))

    def test_it_does_not_mutate_the_record(self) -> None:
        stamped = json.loads(json.dumps(self.RECORD))
        stamped["Body"]["bow-v1"] = [[0.1, 0.2, 0.3]]
        before = json.dumps(stamped, sort_keys=True)
        todo.record_fingerprint(stamped)
        self.assertEqual(before, json.dumps(stamped, sort_keys=True))


class WebOpArgvTest(unittest.TestCase):
    """Each op's argv parses to exactly the fields it means, whatever the request holds."""

    TID = "e7" * 32
    HOSTILE = "--summary=hijack"  # a flag-shaped request field must stay data

    def parsed(self, op: str, target: str, value: str):
        return todo.build_parser().parse_args(todo.WEB_OPS[op].argv(self.TID, target, value))

    def test_the_op_set_is_the_cli_update_surface(self) -> None:
        self.assertEqual(
            {
                "set-summary",
                "set-body",
                "set-ac",
                "set-long-summary",
                "set-actual-summary",
                "note-replace",
                "work-item-replace",
                "work-item-reorder",
            },
            set(todo.WEB_OPS),
        )

    def test_set_ops_write_only_their_own_flag(self) -> None:
        flags = {
            "set-summary": "summary",
            "set-body": "body",
            "set-ac": "ac",
            "set-long-summary": "long_summary",
            "set-actual-summary": "actual_summary",
        }
        for op, dest in flags.items():
            with self.subTest(op=op):
                ns = self.parsed(op, self.HOSTILE, self.HOSTILE)
                self.assertEqual("set", ns.command)
                self.assertEqual(self.TID, ns.id)
                self.assertEqual(self.HOSTILE, getattr(ns, dest))
                others = set(flags.values()) - {dest}
                self.assertEqual({None}, {getattr(ns, other) for other in others})
                self.assertIsNone(ns.state)

    def test_note_replace(self) -> None:
        ns = self.parsed("note-replace", self.HOSTILE, self.HOSTILE)
        self.assertEqual(
            ("note-replace", self.TID, self.HOSTILE, self.HOSTILE),
            (ns.command, ns.selector, ns.target, ns.raw),
        )

    def test_work_item_replace_names_its_target_never_the_cursor(self) -> None:
        ns = self.parsed("work-item-replace", self.HOSTILE, "new words")
        self.assertEqual(
            ("work-item-replace", self.TID, self.HOSTILE, "new words"),
            (ns.command, ns.selector, ns.target, ns.summary),
        )

    def test_work_item_reorder_takes_a_negative_destination(self) -> None:
        ns = self.parsed("work-item-reorder", "objid:0003", "-1")
        self.assertEqual(
            ("work-item-reorder", self.TID, "objid:0003", "-1"),
            (ns.command, ns.selector, ns.src, ns.dst),
        )


class WebUpdaterCase(test_todo.TodoIntegrationCase):
    """A real store, todo.main() in-process, and the WebUpdater that `web --write` injects."""

    TID = "e7" * 32

    def setUp(self) -> None:
        super().setUp()
        self.write_ticket("e7e7e7e7-web", self.TID, "web edits", body="original body")
        self.updater = todo.WebUpdater(self.REPO)

    def in_env(self):
        """The environment a `todo.py web` process would run the updater in."""
        todo_store.reset_store()
        todo.todo_db.reset_todo_dir()
        todo._REPO_KEY_CACHE.clear()
        return mock.patch.dict(os.environ, self._env, clear=True)

    def stored(self) -> Dict[str, Any]:
        return self.read_cur()

    def page_token(self) -> str:
        """The token a freshly loaded page carries."""
        with self.in_env():
            return self.updater.token(self.stored())

    def update(self, **request: Any) -> Dict[str, Any]:
        full = {"id": self.TID, "target": "", "token": self.page_token(), **request}
        with self.in_env():
            return self.updater.update(full)


class WebUpdaterSetBodyTest(WebUpdaterCase):
    """set-body through the CLI's own `set --body`, guarded by the page token."""

    def test_save_with_a_fresh_token_writes_the_body(self) -> None:
        result = self.update(op="set-body", value="edited from the page")
        stored = self.stored()
        self.assertEqual("edited from the page", stored["Body"]["raw"])
        self.assertEqual(todo.record_fingerprint(stored), result["token"])

    def test_the_token_survives_reads(self) -> None:
        self.assertEqual(self.page_token(), self.page_token())

    def test_stale_token_is_a_conflict_carrying_the_stored_body(self) -> None:
        stale = self.page_token()
        proc = self.todo("set", self.TID, "--body=written by the cli")
        self.assertEqual(0, proc.returncode, proc.stderr)
        with self.in_env(), self.assertRaises(todo_web.UpdateConflict) as caught:
            self.updater.update(
                {"id": self.TID, "op": "set-body", "target": "", "value": "draft", "token": stale}
            )
        self.assertEqual("written by the cli", caught.exception.current)
        self.assertEqual(todo.record_fingerprint(self.stored()), caught.exception.token)
        self.assertEqual("written by the cli", self.stored()["Body"]["raw"])

    def test_unknown_todo_is_the_cli_refusal(self) -> None:
        with self.in_env(), self.assertRaises(todo_web.UpdateRefused) as caught:
            self.updater.update(
                {"id": "ffff" * 16, "op": "set-body", "target": "", "value": "x", "token": "t"}
            )
        self.assertIn("no todo found for id", str(caught.exception))

    def test_edit_sentinel_is_the_cli_refusal_not_an_editor(self) -> None:
        with self.assertRaises(todo_web.UpdateRefused) as caught:
            self.update(op="set-body", value="EDIT")
        self.assertIn("requires an interactive terminal", str(caught.exception))
        self.assertEqual("original body", self.stored()["Body"]["raw"])

    def test_unknown_op_is_refused_and_writes_nothing(self) -> None:
        before = self.stored()
        with self.assertRaises(todo_web.UpdateRefused) as caught:
            self.update(op="rm", value="")
        self.assertIn("rm", str(caught.exception))
        self.assertEqual(before, self.stored())

    def test_non_string_value_is_refused(self) -> None:
        with self.assertRaises(todo_web.UpdateRefused):
            self.update(op="set-body", value=["not", "text"])
        self.assertEqual("original body", self.stored()["Body"]["raw"])

    def test_check_and_write_happen_under_one_lock_hold(self) -> None:
        seen: List[str] = []
        real_fingerprint = todo.record_fingerprint
        real_write = todo.write_todo_worktree

        def fingerprint(record: Dict[str, Any]) -> str:
            seen.append("check:" + str(self.TID in todo_store.held_locks()))
            return real_fingerprint(record)

        def write(*args: Any, **kwargs: Any) -> None:
            seen.append("write:" + str(self.TID in todo_store.held_locks()))
            real_write(*args, **kwargs)

        token = self.page_token()
        with mock.patch.object(todo, "record_fingerprint", fingerprint), mock.patch.object(
            todo, "write_todo_worktree", write
        ):
            with self.in_env():
                self.updater.update(
                    {"id": self.TID, "op": "set-body", "target": "", "value": "v", "token": token}
                )
        self.assertEqual("check:True", seen[0])
        self.assertIn("write:True", seen)
        self.assertNotIn("write:False", seen)
        self.assertEqual(set(), todo_store.held_locks())

    def test_a_foreign_lock_holder_makes_the_save_retryable(self) -> None:
        token = self.page_token()
        with self.in_env():
            store = todo_store.get_store()
            store._grace = 0.2
            with mock.patch.object(store, "_try_acquire", return_value=False):
                with self.assertRaises(todo_web.UpdateRefused) as caught:
                    self.updater.update(
                        {
                            "id": self.TID,
                            "op": "set-body",
                            "target": "",
                            "value": "v",
                            "token": token,
                        }
                    )
        self.assertEqual(503, caught.exception.status)
        self.assertEqual("original body", self.stored()["Body"]["raw"])


class WebUpdaterOpsTest(WebUpdaterCase):
    """Every other op, each through its own CLI command, each refusal the CLI's own."""

    def setUp(self) -> None:
        test_todo.TodoIntegrationCase.setUp(self)
        extra = {
            "AC": "original ac",
            "Notes": [{"raw": "first note"}, {"raw": "second note"}],
            "WorkItems": [
                {
                    "summary": "landed",
                    "done": True,
                    "kind": "code",
                    "sha": "a" * 40,
                    "message": "landed",
                },
                {"summary": "open one", "done": False, "kind": "task"},
                {"summary": "open two", "done": False, "kind": "task"},
                {"summary": "open three", "done": False, "kind": "task"},
            ],
        }
        self.write_ticket("e7e7e7e7-web", self.TID, "web edits", body="b", extra=extra)
        self.updater = todo.WebUpdater(self.REPO)

    def objid(self, key: str, index: int) -> str:
        return "objid:" + self.stored()[key][index]["objid"]

    def refused(self, **request: Any) -> str:
        """Run a request that must be refused; assert nothing changed; return the text."""
        before = self.stored()
        with self.assertRaises(todo_web.UpdateRefused) as caught:
            self.update(**request)
        self.assertEqual(400, caught.exception.status)
        self.assertEqual(before, self.stored())
        return str(caught.exception)

    def test_each_set_op_writes_its_field(self) -> None:
        cases = {
            "set-summary": ("Summary", "new summary"),
            "set-ac": ("AC", "new ac"),
            "set-long-summary": ("LongSummary", "new long summary"),
            "set-actual-summary": ("ActualSummary", "new actual summary"),
        }
        for op, (field, value) in cases.items():
            with self.subTest(op=op):
                self.update(op=op, value=value)
                stored = self.stored()[field]
                self.assertEqual(value, stored["raw"] if isinstance(stored, dict) else stored)

    def test_each_set_op_surfaces_the_cli_refusal(self) -> None:
        # `set` captures EDIT through an editor for these flags only; --long-summary
        # takes it literally, so its refusal case is the unknown todo below.
        for op in ("set-summary", "set-ac", "set-actual-summary"):
            with self.subTest(op=op):
                self.assertIn("requires an interactive terminal", self.refused(op=op, value="EDIT"))
        for op in ("set-summary", "set-ac", "set-long-summary", "set-actual-summary"):
            with self.subTest(op=op, case="unknown todo"):
                self.assertIn("no todo found", self.refused(op=op, id="ffff" * 16, value="x"))

    def test_note_replace_rewrites_that_note_only(self) -> None:
        target = self.objid("Notes", 1)
        self.update(op="note-replace", target=target, value="second, rewritten")
        notes = self.stored()["Notes"]
        self.assertEqual(["first note", "second, rewritten"], [n["raw"] for n in notes])
        self.assertEqual(target, "objid:" + notes[1]["objid"])

    def test_note_replace_of_an_unknown_note_is_the_cli_refusal(self) -> None:
        text = self.refused(op="note-replace", target="objid:fff0", value="x")
        self.assertIn("note", text)

    def test_note_replace_conflict_carries_the_stored_note(self) -> None:
        target = self.objid("Notes", 0)
        stale = self.page_token()
        proc = self.todo("note-replace", self.TID, target, "--raw=cli wrote this")
        self.assertEqual(0, proc.returncode, proc.stderr)
        with self.in_env(), self.assertRaises(todo_web.UpdateConflict) as caught:
            self.updater.update(
                {
                    "id": self.TID,
                    "op": "note-replace",
                    "target": target,
                    "value": "d",
                    "token": stale,
                }
            )
        self.assertEqual("cli wrote this", caught.exception.current)

    def test_work_item_replace_rewords_a_not_done_item(self) -> None:
        target = self.objid("WorkItems", 2)
        self.update(op="work-item-replace", target=target, value="open two, reworded")
        items = self.stored()["WorkItems"]
        self.assertEqual("open two, reworded", items[2]["summary"])
        self.assertEqual(target, "objid:" + items[2]["objid"])

    def test_work_item_replace_of_a_done_item_is_the_cli_refusal(self) -> None:
        text = self.refused(op="work-item-replace", target=self.objid("WorkItems", 0), value="x")
        self.assertIn("done", text)

    def test_work_item_reorder_moves_a_not_done_item(self) -> None:
        target = self.objid("WorkItems", 3)
        self.update(op="work-item-reorder", target=target, value="1")
        summaries = [i["summary"] for i in self.stored()["WorkItems"]]
        self.assertEqual(["landed", "open three", "open one", "open two"], summaries)

    def test_work_item_reorder_into_the_done_prefix_is_the_cli_refusal(self) -> None:
        text = self.refused(op="work-item-reorder", target=self.objid("WorkItems", 2), value="0")
        self.assertIn("done prefix", text)

    def test_work_item_reorder_of_a_done_item_is_the_cli_refusal(self) -> None:
        text = self.refused(op="work-item-reorder", target=self.objid("WorkItems", 0), value="2")
        self.assertIn("done", text)

    def test_a_flag_shaped_target_is_never_parsed_as_a_flag(self) -> None:
        self.refused(op="note-replace", target="--raw=hijack", value="x")

    def page_moves(self) -> Dict[str, Dict[str, Any]]:
        """The move requests a write page rendered from the stored record offers."""
        with self.in_env():
            stored = self.stored()
            page = todo_web.render_todo_page(
                Path("."), stored, write=True, token=self.updater.token(stored)
            )
        edits = page_data(page)["write"]["edits"]
        return {k: v for k, v in edits.items() if v["op"] == "work-item-reorder"}

    def test_every_rendered_move_is_accepted_by_the_cli(self) -> None:
        moves = self.page_moves()
        self.assertEqual(4, len(moves))  # three open items: down, up+down, up
        for key in sorted(moves):
            with self.subTest(move=key):
                spec = self.page_moves()[key]
                self.update(op=spec["op"], target=spec["target"], value=spec["value"])
                self.assertEqual("landed", self.stored()["WorkItems"][0]["summary"])

    def test_moving_the_cursor_up_across_the_done_prefix_is_refused(self) -> None:
        moves = self.page_moves()
        cursor = self.objid("WorkItems", 1)
        self.assertNotIn(f"work-item-reorder:{cursor[len('objid:'):]}:up", moves)
        text = self.refused(op="work-item-reorder", target=cursor, value="0")
        self.assertIn("done prefix", text)


if __name__ == "__main__":
    unittest.main()
