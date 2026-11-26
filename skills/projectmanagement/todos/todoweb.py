#!/usr/bin/env python3
"""todoweb: the todo viewer and permalink server (arg parse and policy).

Serves a viewer for a todo and every permalink into it. Every read and every
save goes through ``todo.py`` run as a child process (``todoweb_core.TodoCli``),
so the CLI's own validation, error text, retry status and autocommit apply to
web saves unchanged. This module owns the options, the access levels, the
request checks and the error mapping; ``todoweb_core`` renders pages and runs
the processes. See IMPLEMENTATION.md, "Web access and edits".
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import os
import shlex
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Tuple
from urllib.parse import parse_qs, urlparse

import todo_url
from todoweb_core import (
    _PERMALINK_HEAD,
    JsonDict,
    Reader,
    TodoCli,
    TodoCliError,
    TodoWebError,
    _debug,
    _debug_enabled,
    _DualStackServer,
    git_toplevel,
    read_config_key,
    render_search_page,
    render_todo_page,
    resolve_focus,
)

WILDCARD_HOSTS = ("::", "0.0.0.0")
LOOPBACK_NAMES = ("localhost", "127.0.0.1", "[::1]")
UPDATE_PATH = "/update"
LEVELS = ("none", "read", "write")
ALL_HOST = "::"
LOOPBACK_HOST = "localhost"

# Built-in defaults; config.json "web" and the command line override them.
WEB_DEFAULT_PORT = 8765
WEB_DEFAULT_LOOPBACK = "read"
WEB_DEFAULT_PUBLIC = "none"
WEB_CONFIG_KEY = "web"

LEGACY_JSON_ENV = "TODO_USE_JSON"
# todo.py's exit status when another process holds the store lock.
RETRY_EXIT = 75


def default_bind_host(public: str) -> str:
    """The bind host when none was named: loopback unless public clients are served at all."""
    return LOOPBACK_HOST if public == "none" else ALL_HOST


def is_loopback_client(address: str) -> bool:
    """True when a client's source *address* is loopback: 127.0.0.0/8, ::1, or an
    IPv4-mapped ::ffff:127.x.x.x (what a dual-stack socket reports for a v4 client).

    The address is the TCP peer, not anything the client sent, so it cannot be
    claimed by a header.
    """
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_loopback


class UpdateRefused(TodoWebError):
    """The update command refused; the message is the command's own error text."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


class Updater(Protocol):  # pylint: disable=too-few-public-methods
    """The write side serve() is given for a write class; the viewer never writes itself."""

    def update(self, request: JsonDict) -> JsonDict:
        """Apply ``{id, op, target, value}`` and return the JSON payload of the 200 answer.

        Raises UpdateRefused when the command refuses.
        """


def request_refusal(
    headers: Mapping[str, str], port: int, *, loopback: bool = True
) -> str:
    """Why a write request must be refused before any command runs, or "".

    From a loopback client the Host must be a loopback name on this server's
    port, which a DNS-rebound page cannot send; a public client's Host is only
    required to be present. The Origin must be present and be that same origin,
    which no other page in the browser can claim. The JSON content type cannot
    be sent cross-origin without a CORS preflight, which this server never
    answers.
    """
    host = str(headers.get("Host") or "").strip().lower()
    if loopback:
        if host not in {f"{name}:{port}" for name in LOOPBACK_NAMES}:
            return f"write refused: Host {host!r} is not a loopback name on port {port}"
    elif not host:
        return "write refused: no Host header"
    origin = str(headers.get("Origin") or "").strip().lower()
    if origin != f"http://{host}":
        return f"write refused: Origin {origin!r} is not this viewer's origin http://{host}"
    content_type = (
        str(headers.get("Content-Type") or "").split(";", maxsplit=1)[0].strip().lower()
    )
    if content_type != "application/json":
        return f"write refused: Content-Type {content_type!r} is not application/json"
    return ""


def handle_update(
    headers: Mapping[str, str],
    body: bytes,
    port: int,
    updater: Updater,
    *,
    loopback: bool = True,
) -> "tuple[int, JsonDict]":
    """Check and apply one POST /update; return ``(status, JSON payload)``.

    *loopback* is whether the client is a loopback one (see ``request_refusal``).
    403 when the request fails ``request_refusal`` or its body is not JSON, 400
    when the JSON is not an object, 200 / the refusal's own status from
    *updater*, and 500 naming the exception type and message for any other
    exception it raises. The updater runs only after every check has passed.
    """
    refusal = request_refusal(headers, port, loopback=loopback)
    if refusal:
        return 403, {"error": refusal}
    try:
        request = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return 403, {"error": "write refused: body is not JSON"}
    if not isinstance(request, dict):
        return 400, {"error": "update request must be a JSON object"}
    try:
        return 200, updater.update(request)
    except UpdateRefused as exc:
        return exc.status, {"error": str(exc)}
    except Exception as exc:  # pylint: disable=broad-exception-caught
        # Anything the command raises that is not a refusal still gets an answer; the
        # page shows it instead of a dropped connection.
        return 500, {"error": f"{type(exc).__name__}: {exc}"}


def web_config(basedir: Path) -> Dict[str, Any]:
    """The validated ``web`` object of *basedir*'s config.json; ``{}`` when absent.

    Keys are ``loopback`` and ``public`` (each one of ``LEVELS``), ``host`` (a
    non-empty string) and ``port`` (an integer 0-65535). Anything else raises
    TodoWebError naming the key, so a typo fails at startup instead of silently
    leaving a default in force.
    """
    raw = read_config_key(basedir, WEB_CONFIG_KEY)
    if raw is None:
        return {}
    where = f'config.json "{WEB_CONFIG_KEY}"'
    if not isinstance(raw, dict):
        raise TodoWebError(f"{where} must be an object, not {type(raw).__name__}")
    known = ("loopback", "public", "host", "port")
    unknown = sorted(key for key in raw if key not in known)
    if unknown:
        raise TodoWebError(
            f"{where} has unknown key(s) {', '.join(unknown)}; known: {', '.join(known)}"
        )
    for key in ("loopback", "public"):
        if key in raw and raw[key] not in LEVELS:
            raise TodoWebError(
                f"{where} {key} must be one of {', '.join(LEVELS)}, not {raw[key]!r}"
            )
    if "host" in raw and not (isinstance(raw["host"], str) and raw["host"].strip()):
        raise TodoWebError(
            f"{where} host must be a non-empty string, not {raw['host']!r}"
        )
    if "port" in raw:
        port = raw["port"]
        if (
            isinstance(port, bool)
            or not isinstance(port, int)
            or not 0 <= port <= 65535
        ):
            raise TodoWebError(f"{where} port must be an integer 0-65535, not {port!r}")
    return dict(raw)


@dataclass(frozen=True)
class WebOp:
    """One web edit: the todo.py argv that applies it."""

    argv: Callable[[str, str, str], List[str]]  # (todo_id, target, value)


def _web_set_op(flag: str) -> WebOp:
    """A `set --<flag>=<value>` edit of a text field."""
    return WebOp(
        argv=lambda tid, _target, value: ["set", f"--{flag}={value}", "--", tid]
    )


# todo.py's update surface and nothing else: no op creates, deletes or closes
# anything. Every positional follows "--", flags before it, so no request field
# can be parsed as a flag (the "--" must precede ALL positionals: argparse
# fills an optional positional with nothing before a later "--").
WEB_OPS: Dict[str, WebOp] = {
    "set-summary": _web_set_op("summary"),
    "set-body": _web_set_op("body"),
    "set-ac": _web_set_op("ac"),
    "set-long-summary": _web_set_op("long-summary"),
    "set-actual-summary": _web_set_op("actual-summary"),
    "note-replace": WebOp(
        argv=lambda tid, target, value: [
            "note-replace",
            f"--raw={value}",
            "--",
            tid,
            target,
        ],
    ),
    "work-item-replace": WebOp(
        argv=lambda tid, target, value: [
            "work-item-replace",
            f"--summary={value}",
            "--",
            tid,
            target,
        ],
    ),
    # value is the destination index, as work-item-reorder's DST.
    "work-item-reorder": WebOp(
        argv=lambda tid, target, value: ["work-item-reorder", "--", tid, target, value],
    ),
}


def _refused(exc: TodoCliError) -> UpdateRefused:
    """The UpdateRefused a failed todo.py run answers with: 503 when retryable, else 400."""
    return UpdateRefused(str(exc), status=503 if exc.code == RETRY_EXIT else 400)


class WebUpdater:  # pylint: disable=too-few-public-methods
    """The write side serve() is given for a write class (an ``Updater``).

    Each update runs the matching todo.py command as a child process, so its
    validation, refusals and autocommit are the CLI's, verbatim. A save is
    last-write-wins: it applies whatever the page sent, whether or not the todo
    changed since the page loaded. Updates are serialized in this process.
    """

    def __init__(self, client: TodoCli) -> None:
        self.client = client
        self._serial = threading.Lock()

    def update(self, request: JsonDict) -> JsonDict:
        """Apply one ``{id, op, target, value}`` request; return ``{}``.

        Raises ``UpdateRefused`` with the CLI's error text when the request or
        the command is refused.
        """
        op_name = request.get("op")
        op = WEB_OPS.get(op_name) if isinstance(op_name, str) else None
        if op is None:
            raise UpdateRefused(
                f"unknown web op {op_name!r}; known: {', '.join(sorted(WEB_OPS))}"
            )
        fields = {name: request.get(name) for name in ("id", "target", "value")}
        for name, value in fields.items():
            if not isinstance(value, str):
                raise UpdateRefused(f"{op_name}: {name} must be a string")
        if os.environ.get(LEGACY_JSON_ENV) == "1":
            raise UpdateRefused(
                "web edits need the todo store, not legacy TODO.json mode"
            )
        with self._serial:
            try:
                todo_id = str(self.client.read(fields["id"])["Id"])
                self.client.check(op.argv(todo_id, fields["target"], fields["value"]))
            except TodoCliError as exc:
                raise _refused(exc) from exc
            return {}


# pylint: disable-next=too-many-arguments,too-many-locals,too-many-statements
def serve(
    root: Path,
    *,
    host: Optional[str] = None,
    port: int = WEB_DEFAULT_PORT,
    initial_id: Optional[str] = None,
    resolver: Callable[[str], "tuple[Path, JsonDict]"],
    searcher: Callable[[str], List[JsonDict]],
    loopback: str = "read",
    public: str = "none",
    updater: Optional[Updater] = None,
    reader_factory: Optional[Callable[[], Reader]] = None,
) -> str:
    """Start the viewer and serve until interrupted.

    ``?id=<selector>`` renders that todo via *resolver*, which returns the
    ``(repo_root, todo)`` pair (the repo is where that todo's diffs come from).
    A bare path renders the search page, whose box calls ``/search?q=`` -> a
    JSON list of rows from *searcher(query)* (an empty query lists all todos).
    *initial_id* only shapes the printed URL so the browser opens straight onto
    that todo. *reader_factory* gives each page a fresh reader for the subtodo
    and parent boxes; without one they render from the todo's own snapshot.

    *loopback* governs clients whose source address is loopback and *public*
    every other client, each one of ``LEVELS``: ``none`` answers 403 to every
    request, ``read`` serves GET and answers 403 to any POST, ``write`` also
    accepts ``POST /update`` through ``handle_update`` to *updater* (required
    when either is ``write``). Both ``none`` is refused before anything binds.
    The class is decided per request from the connection's peer address.
    """
    _debug(
        f"serve host={host} port={port} root={root} initial_id={initial_id} "
        f"loopback={loopback} public={public}",
        phase="serve",
    )
    for name, level in (("loopback", loopback), ("public", public)):
        if level not in LEVELS:
            raise TodoWebError(
                f"{name} must be one of {', '.join(LEVELS)}, not {level!r}"
            )
    if loopback == "none" and public == "none":
        raise TodoWebError("loopback and public are both none: nothing could connect")
    if "write" in (loopback, public) and updater is None:
        raise TodoWebError("write mode needs an updater")
    if host is None:
        host = default_bind_host(public)

    def new_reader() -> Optional[Reader]:
        return reader_factory() if reader_factory is not None else None

    class Handler(BaseHTTPRequestHandler):
        """One request: access class, then the page, the search rows or the update."""

        def _client_is_loopback(self) -> bool:
            return is_loopback_client(str(self.client_address[0]))

        def _level(self) -> str:
            """The access level of the class this request's client belongs to."""
            return loopback if self._client_is_loopback() else public

        def _forbidden(self) -> bool:
            """Answer 403 and return True when this client's class may not GET."""
            if self._level() != "none":
                return False
            self._respond_json(
                403, {"error": "forbidden: this viewer does not serve you"}
            )
            return True

        def do_POST(self) -> None:  # noqa: N802 pylint: disable=invalid-name
            """Answer POST /update for a write-class client; 403/404 otherwise."""
            level = self._level()
            if level != "write" or updater is None:
                self._respond_json(
                    403, {"error": f"forbidden: this client is at level {level}"}
                )
                return
            if urlparse(self.path).path != UPDATE_PATH:
                self._respond_json(404, {"error": f"no write endpoint at {self.path}"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                self._respond_json(400, {"error": "bad Content-Length"})
                return
            body = self.rfile.read(max(length, 0))
            status, payload = handle_update(
                self.headers,
                body,
                self.server.server_port,
                updater,
                loopback=self._client_is_loopback(),
            )
            self._respond_json(status, payload)

        def _respond_json(self, status: int, payload: JsonDict) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802 pylint: disable=invalid-name
            """Answer the search rows, the search page, a todo page or a permalink."""
            if self._forbidden():
                return
            parsed = urlparse(self.path)
            if parsed.path == "/search":
                query = parse_qs(parsed.query).get("q", [""])[0]
                try:
                    rows = searcher(query)
                except TodoWebError as exc:
                    self.send_error(400, str(exc))
                    return
                self._respond(
                    json.dumps(rows).encode("utf-8"), "application/json; charset=utf-8"
                )
                return
            if parsed.path not in {"/", "/index.html"}:
                if _PERMALINK_HEAD.match(parsed.path):
                    self._permalink(parsed.path)
                    return
                self.send_error(404)
                return
            todo_id = parse_qs(parsed.query).get("id", [None])[0]
            try:
                if todo_id:
                    todo_root, todo = resolver(todo_id)
                    payload = self._page(todo_root, todo, new_reader())
                else:
                    payload = render_search_page(root, searcher(""))
            except TodoWebError as exc:
                self.send_error(400, str(exc))
                return
            self._respond(payload.encode("utf-8"), "text/html; charset=utf-8")

        def _permalink(self, path: str) -> None:
            """Serve /<todoid>/<path...>: the whole todo, focused on that item.

            The path IS the resource -- "todo d56d, focused on objid 23" -- so it
            renders 200 in place. It does not redirect: a permalink that bounced
            you to a different URL would not be the durable name it claims to be,
            and the address bar would stop matching the link you were handed.
            """
            reader = new_reader()
            try:
                selector, segments = todo_url.split_url_path(path)
                todo_root, todo = resolver(selector)
                focus = resolve_focus(todo, segments, reader=reader)
                payload = self._page(todo_root, todo, reader, focus_objid=focus)
            except (todo_url.TodoUrlError, TodoWebError) as exc:
                self.send_error(404, str(exc))
                return
            self._respond(payload.encode("utf-8"), "text/html; charset=utf-8")

        def _page(
            self,
            todo_root: Path,
            todo: JsonDict,
            reader: Optional[Reader],
            *,
            focus_objid: str = "",
        ) -> str:
            """The todo page, with edit controls when this client's class is `write`."""
            return render_todo_page(
                todo_root,
                todo,
                focus_objid=focus_objid,
                write=self._level() == "write" and updater is not None,
                reader=reader,
            )

        def _respond(self, body: bytes, content_type: str) -> None:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def end_headers(self) -> None:
            """Every response, errors included, forbids framing: a page that embeds the
            viewer could otherwise overlay its edit controls (clickjacking)."""
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "frame-ancestors 'none'")
            super().end_headers()

        # BaseHTTPRequestHandler names this parameter `format`.
        # pylint: disable-next=redefined-builtin
        def log_message(self, format: str, *args: object) -> None:
            if os.environ.get("TODO_WEB_LOG") or _debug_enabled():
                super().log_message(format, *args)

    server = _DualStackServer((host, port), Handler)
    shown = (
        "localhost" if host in WILDCARD_HOSTS else f"[{host}]" if ":" in host else host
    )
    base = f"http://{shown}:{server.server_port}"
    url = f"{base}/{initial_id}" if initial_id else base
    print(f"todo web: {url}  loopback={loopback}  public={public}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return url
    finally:
        server.server_close()
    return url


def build_parser() -> argparse.ArgumentParser:
    """The todoweb options: the same ones `todo.py web` takes."""
    parser = argparse.ArgumentParser(
        prog="todoweb",
        description=(
            "Serve a viewer for todos and every permalink into them. Every read and "
            "save runs todo.py as a child process. Access is set per client class, "
            "each none, read or write: --loopback for clients whose source address "
            "is loopback (default read) and --public for every other client "
            '(default none). Every option defaults from the "web" object of the '
            "todo dir's config.json (CLI beats config beats built-in)."
        ),
    )
    parser.add_argument(
        "selector",
        nargs="?",
        default=None,
        help="todo selector: 4+ hex Id prefix or full digest (default: search page)",
    )
    parser.add_argument(
        "--host",
        default=None,
        help=f"bind host (default {LOOPBACK_HOST!r} when --public is none, else "
        f"{ALL_HOST!r}, which serves IPv4 and IPv6)",
    )
    parser.add_argument(
        "--port", type=int, default=None, help=f"bind port (default {WEB_DEFAULT_PORT})"
    )
    parser.add_argument(
        "--loopback",
        choices=LEVELS,
        default=None,
        help="access for loopback clients (default read; config.json web.loopback)",
    )
    parser.add_argument(
        "--public",
        choices=LEVELS,
        default=None,
        help="access for every other client (default none; config.json web.public)",
    )
    parser.add_argument(
        "--dump-html",
        action="store_true",
        help="print the rendered HTML and exit instead of starting a server",
    )
    return parser


def settings(args: argparse.Namespace, basedir: Path) -> Dict[str, Any]:
    """The effective ``loopback``, ``public``, ``host`` and ``port``.

    Precedence per key: the command line, then the ``web`` object of the todo
    dir's config.json, then the built-in default. ``host`` is None when none of
    them names one; ``bind_host`` then derives it from ``public``. A malformed
    ``web`` object raises TodoWebError.
    """
    cli = {
        "loopback": args.loopback,
        "public": args.public,
        "host": args.host,
        "port": args.port,
    }
    configured = web_config(basedir)
    built_in: Dict[str, Any] = {
        "loopback": WEB_DEFAULT_LOOPBACK,
        "public": WEB_DEFAULT_PUBLIC,
        "host": None,
        "port": WEB_DEFAULT_PORT,
    }
    return {
        key: cli[key] if cli[key] is not None else configured.get(key, default)
        for key, default in built_in.items()
    }


def bind_host(merged: Mapping[str, Any]) -> str:
    """The host to bind: the explicit one, else loopback unless public clients are served."""
    if merged["host"] is not None:
        return str(merged["host"])
    return default_bind_host(merged["public"])


def search_rows(client: TodoCli, query: str) -> List[JsonDict]:
    """Rows for the viewer's search box.

    A non-empty query runs the same search as `todo.py search` (rank order
    preserved); an empty query lists every todo. The box has no shell, so it is
    split with ``shlex`` -- a quoted phrase becomes one term, mirroring the CLI
    (unbalanced quotes fall back to whitespace splitting).
    """
    if query.strip():
        try:
            terms = shlex.split(query)
        except ValueError:
            terms = query.split()
        if terms:
            return client.search_rows(terms)
    return client.ls_rows()


def run(args: argparse.Namespace, client: TodoCli) -> int:
    """Serve, or print, the viewer for *args*; raise TodoWebError on a refusal."""
    basedir = client.basedir()
    merged = settings(args, basedir)
    levels = (merged["loopback"], merged["public"])
    if not args.dump_html and levels == ("none", "none"):
        raise TodoWebError(
            "loopback and public are both none, so no client could connect; "
            "set at least one to read or write"
        )
    root = git_toplevel(client.cwd)

    def resolve_todo(selector: str) -> Tuple[Path, JsonDict]:
        """Read one todo through todo.py; its diffs come from this repo."""
        return root, client.read(selector)

    initial_id: Optional[str] = None
    if args.selector is not None:
        initial_id = str(client.read(args.selector).get("Id") or "") or None

    if args.dump_html:
        if initial_id is not None:
            _, ticket = resolve_todo(initial_id)
            page = render_todo_page(
                root,
                ticket,
                write=merged["loopback"] == "write",
                reader=client.reader(),
            )
        else:
            page = render_search_page(basedir, search_rows(client, ""))
        print(page)
        return 0
    serve(
        basedir,
        host=bind_host(merged),
        port=merged["port"],
        initial_id=initial_id,
        resolver=resolve_todo,
        searcher=lambda query: search_rows(client, query),
        loopback=merged["loopback"],
        public=merged["public"],
        updater=WebUpdater(client) if "write" in levels else None,
        reader_factory=client.reader,
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Parse *argv*, run the viewer, and turn a refusal into stderr text and exit 1."""
    args = build_parser().parse_args(argv)
    try:
        return run(args, TodoCli(Path.cwd()))
    except TodoCliError as exc:
        print(f"todoweb: {exc}", file=sys.stderr)
        return RETRY_EXIT if exc.code == RETRY_EXIT else 1
    except TodoWebError as exc:
        print(f"todoweb: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
