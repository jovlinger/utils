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


if __name__ == "__main__":
    unittest.main()
