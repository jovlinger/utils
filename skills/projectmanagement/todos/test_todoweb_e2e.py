"""todoweb end to end: the executable on a free port, against a real store.

Starts ``todoweb.py`` as its own process, fetches a todo page and a permalink,
saves one edit over HTTP, and checks that the record and the store autocommit
are exactly what the same ``todo.py`` command leaves behind.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import unittest
import urllib.request
from typing import Any, Dict, List, Tuple

import todoweb_harness

TID_WEB = "a1" * 32
TID_CLI = "b2" * 32


def _anonymous(record: Dict[str, Any], tid: str) -> str:
    """*record* as JSON with its own Id and write times taken out, for comparing two todos."""
    rest = {
        k: v for k, v in record.items() if k not in ("Id", "create_dt", "update_dt")
    }
    return json.dumps(rest, sort_keys=True).replace(tid[:8], "<id>")


def _page_data(page: str) -> Dict[str, Any]:
    return json.loads(re.search(r"const DATA = (\{.*?\});", page, re.S).group(1))


class TodowebEndToEndTest(todoweb_harness.WebStoreCase):
    """todoweb.py serves pages and permalinks and saves through todo.py."""

    def setUp(self) -> None:
        super().setUp()
        self.git("init", "-q", cwd=self.store_dir)
        self.git("config", "user.email", "t@example.com", cwd=self.store_dir)
        self.git("config", "user.name", "T", cwd=self.store_dir)
        self.write_config(
            {
                "todo_storage": "file://$TODOBASEDIR/storage",
                "autocommit": ["SetCommand"],
            }
        )
        notes = {"Notes": [{"raw": "a note"}]}
        self.seed(TID_WEB, "edited on the web", body="before", extra=notes)
        self.seed(TID_CLI, "edited on the web", body="before", extra=notes)
        self.base = self.start()

    def start(self) -> str:
        """Run todoweb.py with write access on a free port; return its base URL."""
        proc = subprocess.Popen(  # pylint: disable=consider-using-with
            [
                sys.executable,
                str(todoweb_harness.TODOWEB_PY),
                "--host",
                "127.0.0.1",
                "--port",
                "0",
                "--loopback",
                "write",
            ],
            cwd=self.repo,
            env=self.env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(proc.wait)
        self.addCleanup(proc.kill)
        banner = proc.stdout.readline()
        match = re.search(r"(http://\S+)", banner)
        self.assertIsNotNone(
            match, banner + proc.stderr.read() if proc.poll() else banner
        )
        return match.group(1).replace("localhost", "127.0.0.1")

    def get(self, path: str) -> str:
        """GET *path* from the running todoweb; assert 200; return the body."""
        with urllib.request.urlopen(self.base + path, timeout=60) as resp:
            self.assertEqual(200, resp.status)
            return resp.read().decode("utf-8")

    def post(self, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        """POST *payload* to /update as the page itself would; return (status, JSON)."""
        host = self.base[len("http://") :]
        request = urllib.request.Request(
            self.base + "/update",
            data=json.dumps(payload).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Origin": f"http://{host}",
                "Host": host,
            },
        )
        with urllib.request.urlopen(request, timeout=60) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def store_log(self) -> List[str]:
        """Subjects of the store repo's commits, newest first."""
        return self.git("log", "--format=%s", cwd=self.store_dir).splitlines()

    def test_todo_page_and_permalink_render_the_stored_todo(self) -> None:
        """The page shows the stored todo; a permalink opens it focused on the note."""
        page = self.get(f"/{TID_WEB[:8]}")
        self.assertIn("edited on the web", page)
        self.assertEqual(TID_WEB, _page_data(page)["id"])
        note = self.stored(TID_WEB)["Notes"][0]["objid"]
        focused = self.get(f"/{TID_WEB[:8]}/objid/{note}")
        self.assertIn(f'const FOCUS = "{note}"', focused)

    def test_a_save_leaves_what_the_same_cli_command_leaves(self) -> None:
        """A web save and `todo.py set` leave the same record and the same autocommit."""
        spec = _page_data(self.get(f"/{TID_WEB[:8]}"))["write"]["edits"]["set-body"]
        status, payload = self.post(
            {
                "id": TID_WEB,
                "op": spec["op"],
                "target": spec["target"],
                "value": "after",
            }
        )
        self.assertEqual((200, {}), (status, payload))
        web_commit = self.store_log()[0]

        proc = self.todo("set", "--body=after", "--", TID_CLI)
        self.assertEqual(0, proc.returncode, proc.stderr)
        cli_commit = self.store_log()[0]

        web, cli = self.stored(TID_WEB), self.stored(TID_CLI)
        self.assertEqual("after", web["Body"]["raw"])
        self.assertEqual(_anonymous(cli, TID_CLI), _anonymous(web, TID_WEB))
        self.assertEqual(
            cli_commit.replace(TID_CLI[:8], "<id>"),
            web_commit.replace(TID_WEB[:8], "<id>"),
        )

    def test_search_page_lists_every_todo_with_its_full_id(self) -> None:
        """The bare page lists every todo in the store by its full Id."""
        page = self.get("/")
        self.assertIn(TID_WEB, page)
        self.assertIn(TID_CLI, page)


if __name__ == "__main__":
    unittest.main()
