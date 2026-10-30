#!/usr/bin/env python3
"""Tests for the viewer's bind: dual-stack, loopback under --write; no real sockets or DNS."""

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
    """serve() defaults to the dual-stack wildcard and prints a browsable URL."""

    def _printed_url(self, host: str | None) -> str:
        kwargs = {} if host is None else {"host": host}
        fake_server = mock.Mock(server_port=8765)
        fake_server.serve_forever.side_effect = KeyboardInterrupt
        out = io.StringIO()
        with mock.patch.object(todo_web, "_DualStackServer", return_value=fake_server) as cls:
            with redirect_stdout(out):
                todo_web.serve(
                    Path("."), resolver=mock.Mock(), searcher=mock.Mock(), **kwargs
                )
        self.last_address = cls.call_args.args[0]
        return out.getvalue().strip()

    def test_default_host_is_the_ipv6_wildcard(self) -> None:
        default = inspect.signature(todo_web.serve).parameters["host"].default
        self.assertEqual("::", default)

    def test_default_binds_the_wildcard_and_prints_localhost(self) -> None:
        self.assertEqual("http://localhost:8765/", self._printed_url(None))
        self.assertEqual(("::", 8765), self.last_address)

    def test_ipv4_wildcard_prints_localhost(self) -> None:
        self.assertEqual("http://localhost:8765/", self._printed_url("0.0.0.0"))

    def test_ipv6_literal_prints_bracketed(self) -> None:
        self.assertEqual("http://[::1]:8765/", self._printed_url("::1"))

    def test_ipv4_literal_prints_as_given(self) -> None:
        self.assertEqual("http://127.0.0.1:8765/", self._printed_url("127.0.0.1"))

    def test_serve_is_read_only_by_default(self) -> None:
        default = inspect.signature(todo_web.serve).parameters["write"].default
        self.assertIs(False, default)


class WebCommandBindTest(unittest.TestCase):
    """`todo.py web` binds dual-stack read-only, loopback under --write, --host as given."""

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

    def test_default_is_read_only_on_the_dual_stack_wildcard(self) -> None:
        kwargs = self._serve_kwargs()
        self.assertEqual("::", kwargs["host"])
        self.assertIs(False, kwargs["write"])
        self.assertIsNone(kwargs["updater"])

    def test_write_binds_loopback_and_enables_writes(self) -> None:
        kwargs = self._serve_kwargs("--write")
        self.assertEqual("localhost", kwargs["host"])
        self.assertIs(True, kwargs["write"])
        self.assertIsInstance(kwargs["updater"], todo.WebUpdater)

    def test_explicit_host_is_honoured_under_write(self) -> None:
        kwargs = self._serve_kwargs("--write", "--host", "0.0.0.0")
        self.assertEqual("0.0.0.0", kwargs["host"])
        self.assertIs(True, kwargs["write"])

    def test_explicit_host_is_honoured_read_only(self) -> None:
        kwargs = self._serve_kwargs("--host", "127.0.0.1")
        self.assertEqual("127.0.0.1", kwargs["host"])
        self.assertIs(False, kwargs["write"])

    def test_loopback_name_prints_as_given(self) -> None:
        fake_server = mock.Mock(server_port=8765)
        fake_server.serve_forever.side_effect = KeyboardInterrupt
        out = io.StringIO()
        with mock.patch.object(todo_web, "_DualStackServer", return_value=fake_server):
            with redirect_stdout(out):
                todo_web.serve(
                    Path("."), host="localhost", resolver=mock.Mock(), searcher=mock.Mock()
                )
        self.assertEqual("http://localhost:8765/", out.getvalue().strip())


if __name__ == "__main__":
    unittest.main()
