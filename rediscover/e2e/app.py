"""Sample instrumented HTTP server for E2E testing.

Endpoints:
  GET /work?n=5   — calls do_work(n) which sleeps 10 ms per iteration
  GET /health     — returns 200 OK
"""

from __future__ import annotations

import os
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import rediscover

REDIS_URLS = os.environ.get("REDIS_URLS", "redis://localhost:6379").split(",")
APP_NAMESPACE = os.environ.get("APP_NAMESPACE", "default")
PORT = int(os.environ.get("PORT", "8765"))

rediscover.configure(REDIS_URLS, namespace=APP_NAMESPACE)


# The do_work function is decorated with @profile from rediscover.
# Each GET /work call drives the counter up, allowing the E2E test to
# assert exact counts via the management CLI.
@rediscover.profile(name="do_work")
def do_work(n: int) -> None:
    for _ in range(n):
        time.sleep(0.01)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # suppress default access log noise

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._respond(200, b"OK")
        elif parsed.path == "/work":
            qs = parse_qs(parsed.query)
            n = int(qs.get("n", ["1"])[0])
            do_work(n)
            self._respond(200, f"done n={n}".encode())
        else:
            self._respond(404, b"not found")

    def _respond(self, code: int, body: bytes) -> None:
        self.send_response(code)
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"rediscover sample app listening on :{PORT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        rediscover.close()
