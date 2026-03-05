"""Serve the thermo UI on port 8080. Plain HTML form POST to app on port 5000."""

import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Dict, List, Optional

PORT_UI = int(os.environ.get("UI_PORT", "8080"))


def _parse_timer(s: str) -> Optional[int]:
    """Parse timer: minutes (int) or time-of-day (HH:MM or H:MM). Returns minutes from midnight."""
    s = s.strip()
    if not s:
        return None
    # Time of day: 6:30, 18:30, 9:05
    m = re.match(r"^(\d{1,2}):(\d{2})$", s)
    if m:
        h, mm = int(m.group(1)), int(m.group(2))
        if 0 <= h <= 23 and 0 <= mm <= 59:
            return h * 60 + mm
        return None
    try:
        val = int(s)
        if 0 <= val <= 1439:
            return val
    except ValueError:
        pass
    return None


def _minutes_to_time(minutes: int) -> str:
    """Format minutes from midnight as HH:MM."""
    h, m = divmod(minutes, 60)
    return f"{h}:{m:02d}"


PORT_APP = int(os.environ.get("PORT", "5000"))
APP_BASE = f"http://127.0.0.1:{PORT_APP}"

TEMPLATE_PATH = Path(__file__).parent / "ui_template.html"


def _format_time(iso: Optional[str]) -> str:
    """Format ISO timestamp as HH:MM."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except (ValueError, TypeError):
        return ""


def _format_log_line(line: str) -> str:
    """Format log line: bold datetime, escape HTML. One line per entry."""
    import html

    # Match leading datetime: 2026-03-05T21:23:17.123
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\s*(.*)$", line)
    if m:
        return f"<b>{html.escape(m.group(1))}</b> {html.escape(m.group(2))}"
    return html.escape(line)


def _fetch_logs() -> str:
    """Fetch logs from app, format with bold datetime, one per line."""
    try:
        with urllib.request.urlopen(f"{APP_BASE}/logs", timeout=2) as r:
            d = __import__("json").loads(r.read().decode())
        lines = d.get("lines", [])
        if not lines:
            return ""
        return "<br>".join(_format_log_line(ln) for ln in lines)
    except Exception:
        return ""


def _fetch_env() -> str:
    try:
        with urllib.request.urlopen(f"{APP_BASE}/environment", timeout=2) as r:
            d = __import__("json").loads(r.read().decode())
            t = d.get("temperature_centigrade")
            h = d.get("humidity_percent")
            ts = _format_time(d.get("time"))
            base = f"{t}°C, {h}%" if t is not None and h is not None else "—"
            return f"{base} at {ts}" if base != "—" and ts else base
    except Exception:
        return "—"


def _form_to_command(form: Dict[bytes, List[bytes]]) -> dict:
    cmd: dict = {
        "power": b"power" in form,
        "mode": (form.get(b"mode") or [b"AUTO"])[0].decode(),
        "fan": (form.get(b"fan") or [b"AUTO"])[0].decode(),
        "swing": b"swing" in form,
        "powerful": b"powerful" in form,
        "econo": b"econo" in form,
        "comfort": b"comfort" in form,
    }
    t = (form.get(b"temp_c") or [b""])[0].decode().strip()
    if t:
        try:
            cmd["temp_c"] = float(t)
        except ValueError:
            pass
    # Timer on: only set if enable checkbox checked; HH:MM format
    if b"timer_on_enable" in form:
        on = (form.get(b"timer_on_minutes") or [b""])[0].decode().strip()
        parsed = _parse_timer(on)
        cmd["timer_on_minutes"] = parsed  # None if invalid/blank
    else:
        cmd["timer_on_minutes"] = None
    # Timer off: same
    if b"timer_off_enable" in form:
        off = (form.get(b"timer_off_minutes") or [b""])[0].decode().strip()
        parsed = _parse_timer(off)
        cmd["timer_off_minutes"] = parsed
    else:
        cmd["timer_off_minutes"] = None
    return cmd


def render_template(state: "State", env: str = "—", msg: str = "") -> str:
    from heatpumpirctl import Mode, Fan, State

    def opt(val: str, sel: str) -> str:
        c = " selected" if val == sel else ""
        return f'<option value="{val}"{c}>{val}</option>'

    mode_opts = "".join(opt(m.name, state.mode.name) for m in Mode)
    fan_opts = "".join(opt(f.name, state.fan.name) for f in Fan)

    logs_html = _fetch_logs()
    return (
        TEMPLATE_PATH.read_text()
        .replace("$env", env)
        .replace("$msg", msg)
        .replace("$logs", logs_html)
        .replace("$power_checked", "checked" if state.power else "")
        .replace("$swing_checked", "checked" if state.swing else "")
        .replace("$powerful_checked", "checked" if state.powerful else "")
        .replace("$econo_checked", "checked" if state.econo else "")
        .replace("$comfort_checked", "checked" if state.comfort else "")
        .replace("$mode_options", mode_opts)
        .replace("$fan_options", fan_opts)
        .replace(
            "$temp_c",
            (
                str(int(state.temp_c))
                if state.temp_c == int(state.temp_c)
                else str(state.temp_c)
            ),
        )
        .replace(
            "$timer_on_checked", "checked" if state.timer_on_minutes is not None else ""
        )
        .replace(
            "$timer_on_disabled",
            "" if state.timer_on_minutes is not None else "disabled",
        )
        .replace(
            "$timer_on",
            (
                _minutes_to_time(state.timer_on_minutes)
                if state.timer_on_minutes is not None
                else ""
            ),
        )
        .replace(
            "$timer_off_checked",
            "checked" if state.timer_off_minutes is not None else "",
        )
        .replace(
            "$timer_off_disabled",
            "" if state.timer_off_minutes is not None else "disabled",
        )
        .replace(
            "$timer_off",
            (
                _minutes_to_time(state.timer_off_minutes)
                if state.timer_off_minutes is not None
                else ""
            ),
        )
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path.startswith("/?"):
            from heatpumpirctl import State

            html = render_template(State(), env=_fetch_env())
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            form = urllib.parse.parse_qs(body)
            cmd = _form_to_command(form)
            msg = self._post_daikin(cmd)
            from heatpumpirctl import State

            state = State.from_json(cmd)
            html = render_template(state, env=_fetch_env(), msg=msg)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html.encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()

    def _post_daikin(self, cmd: dict) -> str:
        import json

        body = json.dumps({"command": cmd}).encode()
        req = urllib.request.Request(f"{APP_BASE}/daikin", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                d = json.loads(r.read().decode())
                status = "Sent" if d.get("sent") else "Stored"
                ts = _format_time(d.get("time"))
                return f"{status} at {ts}." if ts else f"{status}."
        except urllib.error.HTTPError as e:
            d = json.loads(e.read().decode()) if e.read() else {}
            return f"Error: {d.get('error', e.code)}"
        except Exception as e:
            return f"Error: {e}"

    def log_message(self, format: str, *args: object) -> None:
        pass


def main() -> None:
    server = HTTPServer(("0.0.0.0", PORT_UI), Handler)
    print(f"UI on http://0.0.0.0:{PORT_UI}")
    server.serve_forever()


if __name__ == "__main__":
    main()
