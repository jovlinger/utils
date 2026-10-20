#!/usr/bin/env python3
"""Egress proxies for the Render Tailscale node.

SOCKS5 on $SOCKS_PORT (1080) and an HTTP proxy on $HTTP_PROXY_PORT (1055)
dial the public internet with normal sockets. Tailscale Serve publishes
those ports on the node 100.x address. $PORT (Render sets this) serves
/healthz so the free web service has an HTTP listener.

Render sleeps a free web service 15 minutes after the last inbound request
on its public URL. Tailscale traffic does not arrive there. While a proxy
connection is open, this process GETs $RENDER_EXTERNAL_URL/healthz so that
clock resets, and repeats that every few minutes until the client leaves.
"""

from __future__ import annotations

import json
import os
import select
import socket
import socketserver
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional, Sequence, Tuple

IpLookup = Callable[[], Optional[str]]


def tailscale_ipv4(socket_path: Optional[str] = None) -> Optional[str]:
    """Return the node's IPv4 tailnet address, or None when it is not up."""
    path = socket_path or os.environ.get("TS_SOCKET", "/tmp/tailscale/tailscaled.sock")
    try:
        proc = subprocess.run(
            ["tailscale", f"--socket={path}", "ip", "-4"],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    for line in proc.stdout.split():
        if line.startswith("100."):
            return line
    return None


def _pipe(left: socket.socket, right: socket.socket) -> None:
    pair = [left, right]
    try:
        while True:
            readable, _, _ = select.select(pair, [], [], 60)
            if not readable:
                break
            for src in readable:
                dst = right if src is left else left
                try:
                    data = src.recv(65536)
                except OSError:
                    return
                if not data:
                    return
                try:
                    dst.sendall(data)
                except OSError:
                    return
    finally:
        for sock in pair:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass


def _read_exact(conn: socket.socket, count: int) -> bytes:
    buf = bytearray()
    while len(buf) < count:
        chunk = conn.recv(count - len(buf))
        if not chunk:
            raise ConnectionError("short read")
        buf.extend(chunk)
    return bytes(buf)


def _socks_reply(conn: socket.socket, rep: int) -> None:
    conn.sendall(bytes((5, rep, 0, 1, 0, 0, 0, 0, 0, 0)))


# Render's free-tier idle window is 15 minutes. Ping well inside it.
KEEPALIVE_INTERVAL: float = 4 * 60


class _ProxyActivity:
    """Tracks proxy connections so the public-URL ping runs only while used."""

    def __init__(self) -> None:
        self._open = 0
        self._since_ping = False
        self._cond = threading.Condition()

    def enter(self) -> None:
        with self._cond:
            self._open += 1
            self._since_ping = True
            self._cond.notify_all()

    def leave(self) -> None:
        with self._cond:
            if self._open > 0:
                self._open -= 1

    def wants_ping(self) -> bool:
        with self._cond:
            return self._open > 0 or self._since_ping

    def note_ping(self) -> None:
        with self._cond:
            self._since_ping = False

    def wait_for_work(self, timeout: float) -> None:
        with self._cond:
            if self._open > 0 or self._since_ping:
                return
            self._cond.wait(timeout)


_activity = _ProxyActivity()


def public_keepalive_url() -> Optional[str]:
    """Public /healthz URL, or None when Render did not set one."""
    base = os.environ.get("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
    if not base:
        return None
    return base + "/healthz"


def fetch_public(url: str) -> None:
    """GET url. The request has to leave the container and come back through Render's edge."""
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=10) as resp:
        resp.read(65536)


def run_keepalive(
    url: str,
    fetch: Callable[[str], None],
    interval: float,
    stop: threading.Event,
    activity: _ProxyActivity,
) -> None:
    """Request url soon after proxy use, then every interval while use continues."""
    last = 0.0
    while not stop.is_set():
        if not activity.wants_ping():
            activity.wait_for_work(0.5)
            continue
        remaining = interval - (time.monotonic() - last)
        if remaining > 0:
            if stop.wait(remaining):
                return
            continue
        try:
            fetch(url)
        except (OSError, urllib.error.URLError) as exc:
            print(f"keepalive: {url} failed: {exc}", flush=True)
        else:
            print(f"keepalive: {url}", flush=True)
        last = time.monotonic()
        activity.note_ping()


def handle_socks(conn: socket.socket) -> None:
    """Serve one SOCKS5 CONNECT (no authentication)."""
    _activity.enter()
    try:
        _serve_socks(conn)
    finally:
        _activity.leave()


def _serve_socks(conn: socket.socket) -> None:
    conn.settimeout(30)
    try:
        header = _read_exact(conn, 2)
        if header[0] != 5:
            return
        methods = _read_exact(conn, header[1])
        if 0 not in methods:
            conn.sendall(b"\x05\xff")
            return
        conn.sendall(b"\x05\x00")
        req = _read_exact(conn, 4)
        if req[0] != 5 or req[1] != 1:
            _socks_reply(conn, 7)
            return
        atyp = req[3]
        if atyp == 1:
            host = socket.inet_ntoa(_read_exact(conn, 4))
        elif atyp == 3:
            length = _read_exact(conn, 1)[0]
            host = _read_exact(conn, length).decode("utf-8")
        elif atyp == 4:
            host = socket.inet_ntop(socket.AF_INET6, _read_exact(conn, 16))
        else:
            _socks_reply(conn, 8)
            return
        port = int.from_bytes(_read_exact(conn, 2), "big")
        try:
            upstream = socket.create_connection((host, port), timeout=20)
        except OSError:
            _socks_reply(conn, 5)
            return
        _socks_reply(conn, 0)
        conn.settimeout(None)
        upstream.settimeout(None)
        _pipe(conn, upstream)
    except (ConnectionError, OSError, UnicodeError):
        return


def _split_host_port(target: str, default_port: int) -> Tuple[str, int]:
    if target.startswith("["):
        end = target.find("]")
        host = target[1:end]
        rest = target[end + 1 :]
        if rest.startswith(":"):
            return host, int(rest[1:])
        return host, default_port
    host, sep, port_text = target.rpartition(":")
    if not sep or not port_text.isdigit():
        return target, default_port
    return host, int(port_text)


def _read_headers(conn: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        chunk = conn.recv(4096)
        if not chunk:
            raise ConnectionError("short read")
        data.extend(chunk)
        if len(data) > 65536:
            raise ConnectionError("headers too large")
    return bytes(data)


def handle_http_proxy(conn: socket.socket) -> None:
    """Serve one HTTP proxy request (CONNECT, or an absolute-form GET)."""
    _activity.enter()
    try:
        _serve_http_proxy(conn)
    finally:
        _activity.leave()


def _serve_http_proxy(conn: socket.socket) -> None:
    conn.settimeout(30)
    try:
        raw = _read_headers(conn)
    except (ConnectionError, OSError):
        return
    head, rest = raw.split(b"\r\n\r\n", 1)
    lines = head.decode("iso-8859-1").split("\r\n")
    parts = lines[0].split(" ")
    if len(parts) < 2:
        return
    method, target = parts[0].upper(), parts[1]
    try:
        if method == "CONNECT":
            host, port = _split_host_port(target, 443)
            upstream = socket.create_connection((host, port), timeout=20)
            conn.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            if rest:
                upstream.sendall(rest)
        else:
            parsed = urllib.parse.urlsplit(target)
            if parsed.scheme != "http" or not parsed.hostname:
                conn.sendall(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\n\r\n")
                return
            host = parsed.hostname
            port = parsed.port or 80
            path = parsed.path or "/"
            if parsed.query:
                path = path + "?" + parsed.query
            origin = f"{method} {path} HTTP/1.1"
            headers = [origin]
            saw_host = False
            for line in lines[1:]:
                if line.lower().startswith("proxy-connection:"):
                    continue
                if line.lower().startswith("host:"):
                    saw_host = True
                headers.append(line)
            if not saw_host:
                headers.append(f"Host: {host}")
            upstream = socket.create_connection((host, port), timeout=20)
            upstream.sendall(("\r\n".join(headers) + "\r\n\r\n").encode("iso-8859-1"))
            if rest:
                upstream.sendall(rest)
    except OSError:
        try:
            conn.sendall(b"HTTP/1.1 502 Bad Gateway\r\nContent-Length: 0\r\n\r\n")
        except OSError:
            pass
        return
    conn.settimeout(None)
    upstream.settimeout(None)
    _pipe(conn, upstream)


class _ThreadingTCPServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _HealthServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True


class _SocksHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        handle_socks(self.request)


class _HttpProxyHandler(socketserver.BaseRequestHandler):
    def handle(self) -> None:
        handle_http_proxy(self.request)


def make_health_handler(
    ip_lookup: IpLookup, socks_port: int, http_port: int
) -> type[BaseHTTPRequestHandler]:
    class HealthHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            path = self.path.split("?", 1)[0]
            if path not in ("/", "/healthz"):
                self.send_error(404)
                return
            body = json.dumps(
                {
                    "ok": True,
                    "tailscale_ip": ip_lookup(),
                    "socks_port": socks_port,
                    "http_port": http_port,
                }
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, fmt: str, *args: object) -> None:
            return

    return HealthHandler


def start_servers(
    host: str = "0.0.0.0",
    http_port: Optional[int] = None,
    socks_port: Optional[int] = None,
    proxy_port: Optional[int] = None,
    ip_lookup: Optional[IpLookup] = None,
    tailscale_socket: Optional[str] = None,
) -> Sequence[socketserver.BaseServer]:
    """Bind the health server and both proxies. Port 0 picks a free port."""
    if http_port is None:
        http_port = int(os.environ.get("PORT", "10000"))
    if socks_port is None:
        socks_port = int(os.environ.get("SOCKS_PORT", "1080"))
    if proxy_port is None:
        proxy_port = int(os.environ.get("HTTP_PROXY_PORT", "1055"))
    lookup = ip_lookup
    if lookup is None:
        socket_path = tailscale_socket

        def lookup() -> Optional[str]:
            return _cached_ip(socket_path)

    socks = _ThreadingTCPServer((host, socks_port), _SocksHandler)
    proxy = _ThreadingTCPServer((host, proxy_port), _HttpProxyHandler)
    health = _HealthServer(
        (host, http_port),
        make_health_handler(
            lookup, int(socks.server_address[1]), int(proxy.server_address[1])
        ),
    )
    return [health, socks, proxy]


_ip_cache: Tuple[float, Optional[str]] = (0.0, None)
_ip_lock = threading.Lock()


def _cached_ip(socket_path: Optional[str]) -> Optional[str]:
    global _ip_cache
    now = time.monotonic()
    with _ip_lock:
        cached_at, cached = _ip_cache
        if now - cached_at < 2:
            return cached
    found = tailscale_ipv4(socket_path)
    with _ip_lock:
        _ip_cache = (time.monotonic(), found)
    return found


def main() -> None:
    servers = start_servers()
    url = public_keepalive_url()
    if url:
        threading.Thread(
            target=run_keepalive,
            args=(url, fetch_public, KEEPALIVE_INTERVAL, threading.Event(), _activity),
            daemon=True,
        ).start()
    threads = []
    for server in servers:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        threads.append(thread)
    try:
        for thread in threads:
            thread.join()
    except KeyboardInterrupt:
        for server in servers:
            server.shutdown()


if __name__ == "__main__":
    main()
