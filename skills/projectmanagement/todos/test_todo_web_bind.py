#!/usr/bin/env python3
"""Tests for the viewer's bind: dual-stack by default, no real sockets or DNS."""

from __future__ import annotations

import inspect
import io
import socket
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import Tuple
from unittest import mock

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


if __name__ == "__main__":
    unittest.main()
