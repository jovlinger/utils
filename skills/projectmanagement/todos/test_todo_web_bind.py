#!/usr/bin/env python3
"""Tests for the viewer's bind and per-class access settings; no real sockets or DNS."""

from __future__ import annotations

import inspect
import io
import re
import socket
import subprocess
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from typing import List, Tuple
from unittest import mock

import todoweb
import todoweb_core
import todoweb_harness


def _bind(host: str) -> Tuple[todoweb._DualStackServer, mock.MagicMock]:
    """Build a server on *host* against a fake socket; return it and the fake."""
    fake = mock.MagicMock()
    fake.getsockname.return_value = (host, 4321)
    with mock.patch("socket.socket", return_value=fake) as make:
        server = todoweb._DualStackServer((host, 0), mock.Mock())
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
        with mock.patch.object(todoweb, "_DualStackServer", return_value=fake_server) as cls:
            with redirect_stdout(out):
                todoweb.serve(Path("."), resolver=mock.Mock(), searcher=mock.Mock(), **kwargs)
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
        with mock.patch.object(todoweb, "_DualStackServer") as cls:
            with self.assertRaises(todoweb.TodoWebError) as caught:
                todoweb.serve(
                    Path("."),
                    resolver=mock.Mock(),
                    searcher=mock.Mock(),
                    loopback="none",
                    public="none",
                )
        self.assertIn("both none", str(caught.exception))
        cls.assert_not_called()

    def test_a_bad_level_refuses_before_binding(self) -> None:
        with mock.patch.object(todoweb, "_DualStackServer") as cls:
            with self.assertRaises(todoweb.TodoWebError):
                todoweb.serve(Path("."), resolver=mock.Mock(), searcher=mock.Mock(), loopback="rw")
        cls.assert_not_called()

    def test_serve_defaults_are_loopback_read_public_none(self) -> None:
        params = inspect.signature(todoweb.serve).parameters
        self.assertEqual(("read", "none"), (params["loopback"].default, params["public"].default))


class WebCommandBindTest(todoweb_harness.WebStoreCase):
    """`todoweb`: loopback=read public=none by default, bind by public, --host as given."""

    def _serve_kwargs(self, *argv: str) -> dict:
        """Run todoweb with serve() faked; return the kwargs serve was called with."""
        args = todoweb.build_parser().parse_args(list(argv))
        with mock.patch.object(todoweb, "serve") as serve:
            self.assertEqual(0, todoweb.run(args, self.client()))
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
        self.assertIsInstance(kwargs["updater"], todoweb.WebUpdater)

    def test_public_write_gets_an_updater(self) -> None:
        kwargs = self._serve_kwargs("--public", "write")
        self.assertIsInstance(kwargs["updater"], todoweb.WebUpdater)

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
        args = todoweb.build_parser().parse_args(["--loopback", "none", "--public", "none"])
        with mock.patch.object(todoweb, "serve") as serve:
            with self.assertRaises(todoweb_core.TodoWebError) as caught:
                todoweb.run(args, self.client())
        self.assertIn("both none", str(caught.exception))
        serve.assert_not_called()

    def test_write_flag_is_gone(self) -> None:
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            todoweb.build_parser().parse_args(["--write"])

    def test_a_level_outside_the_three_is_a_usage_error(self) -> None:
        with mock.patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            todoweb.build_parser().parse_args(["--public", "admin"])

    def test_todo_py_web_takes_the_same_options(self) -> None:
        def options(*argv: str) -> List[str]:
            proc = subprocess.run(
                [sys.executable, *argv, "--help"],
                capture_output=True,
                text=True,
                check=True,
                env=self.env,
            )
            return sorted(set(re.findall(r"(?<![\w-])--[a-z][a-z-]*", proc.stdout)))

        self.assertEqual(
            options(str(todoweb_harness.TODO_PY), "web"),
            options(str(todoweb_harness.TODOWEB_PY)),
        )


class WebConfigTest(todoweb_harness.WebStoreCase):
    """Every web option defaults from config.json "web"; CLI beats config beats built-in."""

    def _config(self, web: object) -> None:
        self.write_config({"web": web})

    def _args(self, *argv: str):
        return todoweb.build_parser().parse_args(list(argv))

    def _settings(self, *argv: str) -> dict:
        return todoweb.settings(self._args(*argv), self.client().basedir())

    def _serve_kwargs(self, *argv: str) -> dict:
        with mock.patch.object(todoweb, "serve") as serve:
            self.assertEqual(0, todoweb.run(self._args(*argv), self.client()))
        return serve.call_args.kwargs

    def _refused(self, *argv: str) -> str:
        with mock.patch.object(todoweb, "serve") as serve:
            with self.assertRaises(todoweb_core.TodoWebError) as caught:
                todoweb.run(self._args(*argv), self.client())
        serve.assert_not_called()
        return str(caught.exception)

    def test_no_config_gives_the_built_in_defaults(self) -> None:
        self.assertEqual(
            {"loopback": "read", "public": "none", "host": None, "port": 8765},
            self._settings(),
        )

    def test_config_supplies_every_option(self) -> None:
        self._config({"loopback": "write", "public": "read", "host": "0.0.0.0", "port": 9100})
        kwargs = self._serve_kwargs()
        self.assertEqual(
            ("write", "read", "0.0.0.0", 9100),
            (kwargs["loopback"], kwargs["public"], kwargs["host"], kwargs["port"]),
        )
        self.assertIsInstance(kwargs["updater"], todoweb.WebUpdater)

    def test_a_partial_config_leaves_the_rest_at_the_built_in_default(self) -> None:
        self._config({"public": "read"})
        kwargs = self._serve_kwargs()
        self.assertEqual(
            ("read", "read", "::", 8765),
            (kwargs["loopback"], kwargs["public"], kwargs["host"], kwargs["port"]),
        )

    def test_the_command_line_beats_config_per_option(self) -> None:
        self._config({"loopback": "write", "public": "read", "host": "0.0.0.0", "port": 9100})
        kwargs = self._serve_kwargs(
            "--loopback", "read", "--public", "none", "--host", "127.0.0.1", "--port", "9200"
        )
        self.assertEqual(
            ("read", "none", "127.0.0.1", 9200),
            (kwargs["loopback"], kwargs["public"], kwargs["host"], kwargs["port"]),
        )
        self.assertIsNone(kwargs["updater"])

    def test_the_bind_default_follows_the_merged_public(self) -> None:
        self._config({"public": "write"})
        self.assertEqual("::", self._serve_kwargs()["host"])
        self.assertEqual("localhost", self._serve_kwargs("--public", "none")["host"])

    def test_config_that_makes_both_none_refuses_to_start(self) -> None:
        self._config({"loopback": "none"})
        self.assertIn("both none", self._refused())

    def test_bad_config_is_refused_with_a_message_naming_the_problem(self) -> None:
        cases = {
            "unknown key": ({"loopbak": "read"}, "loopbak"),
            "bad level": ({"loopback": "rw"}, "loopback must be one of"),
            "bad public level": ({"public": True}, "public must be one of"),
            "empty host": ({"host": " "}, "host must be a non-empty string"),
            "non-string host": ({"host": 7}, "host must be a non-empty string"),
            "string port": ({"port": "8765"}, "port must be an integer"),
            "bool port": ({"port": True}, "port must be an integer"),
            "port too big": ({"port": 70000}, "port must be an integer"),
            "not an object": (["read"], "must be an object"),
        }
        for name, (web, fragment) in cases.items():
            with self.subTest(name):
                self._config(web)
                self.assertIn(fragment, self._refused())

    def test_bad_config_is_refused_even_for_dump_html(self) -> None:
        self._config({"nope": 1})
        self._refused("--dump-html")

    def test_a_cli_value_does_not_rescue_a_bad_config(self) -> None:
        self._config({"loopback": "rw"})
        with self.assertRaises(todoweb_core.TodoWebError):
            self._settings("--loopback", "read")


if __name__ == "__main__":
    unittest.main()
