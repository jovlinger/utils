"""spinmecli connect: errno 65 on the default route must try another iface."""

from __future__ import annotations

import errno
import io
import socket
import unittest
from importlib.machinery import SourceFileLoader
from pathlib import Path
from typing import List, Optional, Tuple
from unittest import mock


def _load():
    path = Path(__file__).resolve().parent / "spinmecli"
    return SourceFileLoader("spinmecli_under_test", str(path)).load_module()


class _FakeSock:
    binds: List[Optional[int]] = []

    def __init__(self, family: int, socktype: int, proto: int) -> None:
        self.family = family
        self.bound: Optional[int] = None
        self.closed = False

    def settimeout(self, timeout: float) -> None:
        self.timeout = timeout

    def setsockopt(self, level: int, opt: int, value: int) -> None:
        self.bound = value

    def connect(self, sockaddr: object) -> None:
        _FakeSock.binds.append(self.bound)
        # Default route (unbound) is the bad ifscope. A pinned iface works.
        if self.bound is None:
            raise OSError(errno.EHOSTUNREACH, "No route to host")

    def close(self) -> None:
        self.closed = True


class SpinmecliRouteTest(unittest.TestCase):
    def test_same_subnet_filters(self) -> None:
        cli = _load()
        rows = [
            ("en0", "192.168.88.59", 11),
            ("en9", "192.168.88.97", 13),
            ("lo0", "127.0.0.1", 1),
        ]
        self.assertEqual(
            cli._same_subnet_ifindexes("192.168.88.45", rows), [11, 13]
        )
        self.assertEqual(cli._same_subnet_ifindexes("10.1.1.1", rows), [])

    def test_unbound_65_then_bound_iface(self) -> None:
        cli = _load()
        _FakeSock.binds = []
        sock = cli._open_tcp(
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            ("192.168.88.45", 80),
            1.0,
            [11, 13],
            socket_factory=_FakeSock,
        )
        self.assertIsInstance(sock, _FakeSock)
        self.assertEqual(_FakeSock.binds, [None, 11])
        self.assertEqual(sock.bound, 11)

    def test_event_help_local_no_device(self) -> None:
        cli = _load()
        text = cli._event_help_text("controller", "list_tasks")
        self.assertIn("event: ListTasks", text)
        self.assertIn("fields: (none)", text)
        status = cli.main(
            ["event", "controller", "DebugStatus", "--help"]
        )
        self.assertEqual(status, 0)

    def test_format_task_list(self) -> None:
        cli = _load()
        out = cli._format_task_list(
            [
                ("controller", ["list_events", "list_tasks"]),
                ("http", []),
            ]
        )
        self.assertEqual(
            out,
            "controller: list_events, list_tasks\nhttp:\n",
        )

    def test_task_list_posts_list_tasks_then_list_events(self) -> None:
        """Happy path: controller/list_tasks then each actor's list_events."""
        cli = _load()
        calls: List[Tuple[str, str]] = []

        def fake_request(
            hostname: str, actor: str, event_name: str, body: str
        ) -> Tuple[int, bytes]:
            self.assertEqual(hostname, "192.168.88.45")
            calls.append((actor, event_name))
            if event_name == "list_tasks":
                self.assertEqual(actor, "controller")
                return 200, b"controller\ntest\n"
            if event_name == "list_events":
                if actor == "controller":
                    return 200, b"list_events,list_tasks"
                if actor == "test":
                    return 200, b"list_events,get_debug"
            self.fail(f"unexpected request {actor}/{event_name} body={body!r}")
            return 500, b"fail"

        with mock.patch.object(cli, "_request", side_effect=fake_request):
            out = io.StringIO()
            err = io.StringIO()
            with mock.patch.object(cli.sys, "stdout", out), mock.patch.object(
                cli.sys, "stderr", err
            ):
                status = cli.main(
                    ["--host", "192.168.88.45", "task", "list"]
                )
        self.assertEqual(status, 0)
        self.assertEqual(
            calls,
            [
                ("controller", "list_tasks"),
                ("controller", "list_events"),
                ("test", "list_events"),
            ],
        )
        self.assertEqual(
            out.getvalue(),
            "controller: list_events, list_tasks\ntest: list_events, get_debug\n",
        )
        self.assertEqual(err.getvalue(), "")

    def test_task_list_surfaces_list_tasks_http_400_unknown_event(self) -> None:
        """Device without list_tasks form map returns 400 unknown event."""
        cli = _load()

        def fake_request(
            hostname: str, actor: str, event_name: str, body: str
        ) -> Tuple[int, bytes]:
            self.assertEqual((actor, event_name), ("controller", "list_tasks"))
            return 400, b"unknown event"

        class _Err:
            def __init__(self) -> None:
                self.text = io.StringIO()
                self.buffer = io.BytesIO()

            def write(self, s: str) -> int:
                return self.text.write(s)

        err = _Err()
        out = io.StringIO()
        with mock.patch.object(cli, "_request", side_effect=fake_request):
            with mock.patch.object(cli.sys, "stdout", out), mock.patch.object(
                cli.sys, "stderr", err
            ):
                status = cli.main(
                    ["--host", "192.168.88.45", "task", "list"]
                )
        self.assertEqual(status, 1)
        self.assertIn("list_tasks HTTP 400", err.text.getvalue())
        self.assertIn(b"unknown event", err.buffer.getvalue())
        self.assertEqual(out.getvalue(), "")

    def test_list_tasks_event_soT_resolves(self) -> None:
        cli = _load()
        te = cli._build_event("list_tasks", {})
        self.assertEqual(te.type_name, "ListTasks")
        self.assertEqual(te.type_id, 0x409)


if __name__ == "__main__":
    unittest.main()