"""MicroPython entry: local debug HTTP on :5000 + canned IR on/off.

Bootstrap: GET /ir/on and /ir/off transmit office Midea cool on/off frames.
Daikin dialect stays in-tree but is not imported or uploaded.

On-device: name this main.py so it runs after soft reset. For interactive REPL
development, prefer mpremote mount (see AGENTS.md).
"""

from __future__ import annotations

import json
import sys
import time
from typing import Optional

import config
import httpdebug
import ir_canned
import ir_tx
from logring import LogRing

try:
    import socket as _socket  # noqa: F401

    _HAS_SOCKET = True
except ImportError:  # pragma: no cover
    _HAS_SOCKET = False


def _monotonic_ms() -> int:
    ticks = getattr(time, "ticks_ms", None)
    if ticks is not None:
        return int(ticks())
    return int(time.monotonic() * 1000)


def _epoch_s() -> int:
    try:
        return int(time.time())
    except Exception:  # noqa: BLE001 -- MP time may be unset
        return 0


class DebugApp:
    """In-memory debug server state (GPIO stubs on host; RMT on device)."""

    def __init__(
        self,
        local_ip: str = config.DEFAULT_LOCAL_IP,
        *,
        ir_dry_run: Optional[bool] = None,
    ) -> None:
        self.boot_ms: int = _monotonic_ms()
        self.logs: LogRing = LogRing(
            config.LOG_CAPACITY,
            boot_ms=self.boot_ms,
            clock_ms=_monotonic_ms,
        )
        self.local_ip: str = local_ip
        self.wifi_ready: bool = False
        self.ntp_ok: bool = False
        self.auth_ed25519_ready: bool = False
        self.pullup_level: int = 1
        self.pulldown_level: int = 0
        # None -> auto (dry on CPython host, RMT on MicroPython).
        self.ir_dry_run: Optional[bool] = ir_dry_run
        self.logs.add("thermo-esp32s3 mp debug boot")

    def uptime_s(self) -> int:
        return max(0, (_monotonic_ms() - self.boot_ms) // 1000)

    def _fire_ir(self, power_on: bool) -> dict:
        body = ir_canned.canned_result(power_on)
        pairs = ir_canned.timings_us(power_on)
        n = ir_tx.transmit_mark_space(
            pairs,
            gpio=config.IR_TX_GPIO,
            dry_run=self.ir_dry_run,
        )
        mode, _ = ir_tx.last_tx_info()
        body["gpio"] = config.IR_TX_GPIO
        body["tx_mode"] = mode
        body["tx_pairs"] = n
        self.logs.add(
            "ir %s gpio=%d pairs=%d mode=%s"
            % (body["action"], config.IR_TX_GPIO, n, mode)
        )
        return body

    def handle_path(self, path: str) -> tuple[int, dict]:
        ir_on = None
        ir_off = None
        if path == "/ir/on":
            ir_on = self._fire_ir(True)
        elif path == "/ir/off":
            ir_off = self._fire_ir(False)

        healthz = httpdebug.build_healthz(
            uptime_s=self.uptime_s(),
            epoch_s=_epoch_s(),
            local_ip=self.local_ip,
            wifi_ready=self.wifi_ready,
            ntp_ok=self.ntp_ok,
            auth_ed25519_ready=self.auth_ed25519_ready,
            pullup_level=self.pullup_level,
            pulldown_level=self.pulldown_level,
            log_lines=self.logs.newest_first(),
        )
        logs = httpdebug.build_logs(self.logs.newest_first())
        gpio = httpdebug.build_gpio(self.pullup_level, self.pulldown_level)
        status, body = httpdebug.route_get(
            path,
            healthz=healthz,
            logs=logs,
            gpio=gpio,
            ir_on=ir_on,
            ir_off=ir_off,
        )
        self.logs.add("req %s -> %d" % (path, status))
        return status, body


def _send_json(conn: object, status: int, body: dict) -> None:
    payload: bytes = json.dumps(body).encode("utf-8")
    status_text: str = "OK" if status == 200 else "Error"
    headers: bytes = (
        "HTTP/1.0 %d %s\r\n"
        "Content-Type: application/json\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n"
        "\r\n" % (status, status_text, len(payload))
    ).encode("ascii")
    conn.send(headers)  # type: ignore[attr-defined]
    conn.send(payload)  # type: ignore[attr-defined]


def _read_request(conn: object, limit: int = 2048) -> str:
    buf: bytes = b""
    while len(buf) < limit:
        chunk: bytes = conn.recv(256)  # type: ignore[attr-defined]
        if not chunk:
            break
        buf += chunk
        if b"\r\n\r\n" in buf or b"\n\n" in buf:
            break
    return buf.decode("utf-8", "ignore")


def serve_forever(app: DebugApp, host: str = "0.0.0.0", port: int = config.HTTP_PORT) -> None:
    if not _HAS_SOCKET:
        raise RuntimeError("socket module unavailable")
    import socket

    srv = socket.socket()
    try:
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    except Exception:  # noqa: BLE001 -- optional on MP
        pass
    srv.bind((host, port))
    srv.listen(2)
    app.logs.add("listen :%d" % port)
    print("esp32s3-office mp listening :%d healthz|logs|gpio|ir/on|ir/off" % port)
    while True:
        conn, _addr = srv.accept()
        try:
            text = _read_request(conn)
            path = httpdebug.parse_request_path(text) if text else "/"
            status, body = app.handle_path(path)
            _send_json(conn, status, body)
        except Exception as exc:  # noqa: BLE001 -- keep server alive
            app.logs.add("handler error: %s" % exc)
        finally:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass


def main() -> None:
    app = DebugApp()
    if "--dry-run-once" in sys.argv:
        status, body = app.handle_path("/healthz")
        print(json.dumps({"status": status, "body": body}))
        return
    if "--ir-on" in sys.argv:
        print(json.dumps(app._fire_ir(True)))
        return
    if "--ir-off" in sys.argv:
        print(json.dumps(app._fire_ir(False)))
        return
    serve_forever(app)


if __name__ == "__main__":
    main()
