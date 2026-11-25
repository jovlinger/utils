#!/usr/bin/env python3
"""Tests for the viewer's bind and per-class access settings; no real sockets or DNS."""

from __future__ import annotations

import inspect
import io
import socket
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Tuple
from unittest import mock

import todo
import todo_web


def _bind(host: str) -> Tuple[todo_web._DualStackServer, mock.MagicMock]:
    """Build a server on *host* against a fake socket; return it and the fake."""
    fake = mock.MagicMock()
    fake.getsockname.return_value = (host, 4321)
    with mock.patch("socket.socket", return_value=fake) as make:
        server = todo_web._DualStackServer((host, 0), mock.Mock())
    make.assert_called_once()
    return server, fake


class DualStackServerTest(unittest.TestCase):
    """_DualStackServer picks the socket family from the host and serves both on ::."""

    def test_ipv6_literal_gets_an_ipv6_socket(self) -> None:
        server, _fake = _bind("::")
        self.assertEqual(socket.AF_INET6, server.address_family)

    def test_wildcard_ipv6_accepts_ipv4_too(self) -> None:
        _server, fake = _bind("::")
        fake.setsockopt.assert_any_call(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)

    def test_ipv4_host_stays_ipv4_and_leaves_v6only_alone(self) -> None:
        server, fake = _bind("127.0.0.1")
        self.assertEqual(socket.AF_INET, server.address_family)
        for call in fake.setsockopt.call_args_list:
            self.assertNotEqual(socket.IPV6_V6ONLY, call.args[1])

    def test_scoped_link_local_gets_an_ipv6_socket(self) -> None:
        server, _fake = _bind("fe80::1853:99b1:a357:bb67%en0")
        self.assertEqual(socket.AF_INET6, server.address_family)

    def test_bind_does_not_resolve_the_hostname(self) -> None:
        """getfqdn on a wildcard host looks up this machine's own name, which can stall."""
        with mock.patch("socket.getfqdn", side_effect=AssertionError("DNS lookup")):
            server, _fake = _bind("::")
        self.assertEqual(4321, server.server_port)


class ServeDefaultsTest(unittest.TestCase):
    """serve() prints one summary banner and binds by who is served."""

    def _banner(self, host: str | None, **kwargs: str) -> str:
        if host is not None:
            kwargs["host"] = host
        fake_server = mock.Mock(server_port=8765)
        fake_server.serve_forever.side_effect = KeyboardInterrupt
        out = io.StringIO()
        with mock.patch.object(todo_web, "_DualStackServer", return_value=fake_server) as cls:
            with redirect_stdout(out):
                todo_web.serve(Path("."), resolver=mock.Mock(), searcher=mock.Mock(), **kwargs)
        self.last_address = cls.call_args.args[0]
        return out.getvalue().strip()

    def test_default_binds_loopback_and_prints_the_summary_line(self) -> None:
        self.assertEqual(
            "todo web: http://localhost:8765  loopback=read  public=none", self._banner(None)
        )
        self.assertEqual(("localhost", 8765), self.last_address)

    def test_the_banner_is_the_only_line(self) -> None:
        self.assertEqual(1, len(self._banner(None).splitlines()))

    def test_banner_states_both_settings(self) -> None:
        banner = self._banner(None, loopback="write", public="read", updater=mock.Mock())
        self.assertEqual("todo web: http://localhost:8765  loopback=write  public=read", banner)

    def test_public_not_none_binds_the_wildcard(self) -> None:
        for public in ("read", "write"):
            with self.subTest(public=public):
                self._banner(None, public=public, updater=mock.Mock())
                self.assertEqual(("::", 8765), self.last_address)

    def test_public_none_binds_loopback_even_when_loopback_is_write(self) -> None:
        self._banner(None, loopback="write", updater=mock.Mock())
        self.assertEqual(("localhost", 8765), self.last_address)

    def test_explicit_host_beats_the_derived_one(self) -> None:
        self._banner("0.0.0.0", public="none")
        self.assertEqual(("0.0.0.0", 8765), self.last_address)

    def test_ipv4_wildcard_prints_localhost(self) -> None:
        self.assertIn("http://localhost:8765  ", self._banner("0.0.0.0"))

    def test_ipv6_literal_prints_bracketed(self) -> None:
        self.assertIn("http://[::1]:8765  ", self._banner("::1"))

    def test_ipv4_literal_prints_as_given(self) -> None:
        self.assertIn("http://127.0.0.1:8765  ", self._banner("127.0.0.1"))

    def test_both_none_refuses_before_binding(self) -> None:
        with mock.patch.object(todo_web, "_DualStackServer") as cls:
            with self.assertRaises(todo_web.TodoWebError) as caught:
                todo_web.serve(
                    Path("."),
                    resolver=mock.Mock(),
                    searcher=mock.Mock(),
                    loopback="none",
                    public="none",
                )
        self.assertIn("both none", str(caught.exception))
        cls.assert_not_called()

    def test_a_bad_level_refuses_before_binding(self) -> None:
        with mock.patch.object(todo_web, "_DualStackServer") as cls:
            with self.assertRaises(todo_web.TodoWebError):
                todo_web.serve(Path("."), resolver=mock.Mock(), searcher=mock.Mock(), loopback="rw")
        cls.assert_not_called()

    def test_serve_defaults_are_loopback_read_public_none(self) -> None:
        params = inspect.signature(todo_web.serve).parameters
        self.assertEqual(("read", "none"), (params["loopback"].default, params["public"].default))


class WebCommandBindTest(unittest.TestCase):
    """`todo.py web`: loopback=read public=none by default, bind by public, --host as given."""

    def _serve_kwargs(self, *argv: str) -> dict:
        """Run `web <argv>` with serve() faked; return the kwargs serve was called with."""
        args = todo.build_parser().parse_args(["web", *argv])
        command = args.command_cls(args, todo_dir=Path("/nonexistent-todo-dir"))
        with mock.patch.object(todo, "repo_root", return_value=Path(".")), mock.patch.object(
            todo.todo_web, "serve"
        ) as serve:
            self.assertEqual(0, command.do())
        serve.assert_called_once()
        return serve.call_args.kwargs

    def test_default_is_loopback_read_public_none_on_loopback(self) -> None:
        kwargs = self._serve_kwargs()
        self.assertEqual("localhost", kwargs["host"])
        self.assertEqual(("read", "none"), (kwargs["loopback"], kwargs["public"]))
        self.assertEqual(8765, kwargs["port"])
        self.assertIsNone(kwargs["updater"])

    def test_loopback_write_gets_an_updater_and_stays_on_loopback(self) -> None:
        kwargs = self._serve_kwargs("--loopback", "write")
        self.assertEqual("localhost", kwargs["host"])
        self.assertEqual("write", kwargs["loopback"])
        self.assertIsInstance(kwargs["updater"], todo.WebUpdater)

    def test_public_write_gets_an_updater(self) -> None:
        kwargs = self._serve_kwargs("--public", "write")
        self.assertIsInstance(kwargs["updater"], todo.WebUpdater)

    def test_public_read_binds_the_dual_stack_wildcard(self) -> None:
        kwargs = self._serve_kwargs("--public", "read")
        self.assertEqual("::", kwargs["host"])
        self.assertIsNone(kwargs["updater"])

    def test_explicit_host_is_honoured_whatever_public_is(self) -> None:
        for argv in (["--host", "0.0.0.0"], ["--host", "0.0.0.0", "--public", "read"]):
            with self.subTest(argv=argv):
                self.assertEqual("0.0.0.0", self._serve_kwargs(*argv)["host"])

    def test_explicit_port_is_passed_on(self) -> None:
        self.assertEqual(9001, self._serve_kwargs("--port", "9001")["port"])

    def test_both_none_refuses_to_start_and_binds_nothing(self) -> None:
        args = todo.build_parser().parse_args(["web", "--loopback", "none", "--public", "none"])
        command = args.command_cls(args, todo_dir=Path("/nonexistent-todo-dir"))
        with mock.patch.object(todo, "repo_root", return_value=Path(".")), mock.patch.object(
            todo.todo_web, "serve"
        ) as serve:
            with self.assertRaises(todo.TodoError) as caught:
                command.do()
        self.assertIn("both none", str(caught.exception))
        serve.assert_not_called()

    def test_write_flag_is_gone(self) -> None:
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            todo.build_parser().parse_args(["web", "--write"])

    def test_a_level_outside_the_three_is_a_usage_error(self) -> None:
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            todo.build_parser().parse_args(["web", "--public", "admin"])


if __name__ == "__main__":
    unittest.main()
