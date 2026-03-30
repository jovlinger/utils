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
    """Format ISO timestamp as HH:MM:SS."""
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return ""


def _format_log_line(line: str) -> str:
    """Format log line: bold datetime, escape HTML. One line per entry."""
    import html

    # Match leading datetime: 2026-03-05T21:23:17.123 or ...17.123Z
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z?)\s*(.*)$", line)
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
            if t is None or h is None:
                return "—°C, —% time=" + (ts or "—")
            # Keep UI env line stable for tests: "<temp>°C, <humidity>%"
            return f"{t}°C, {h}% time={ts or '—'}"
    except Exception:
        return "—"


def _post_json(url: str, body: dict, headers: Optional[Dict[str, str]] = None) -> dict:
    """POST JSON and parse JSON response (or raise)."""
    import json

    req_headers: Dict[str, str] = {"Content-Type": "application/json", "Accept": "application/json"}
    if headers:
        req_headers.update(headers)
    body_bytes = json.dumps(body).encode()
    req = urllib.request.Request(url, data=body_bytes, method="POST")
    for k, v in req_headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=5) as r:
        return __import__("json").loads(r.read().decode())


def _fetch_manage_status(token: str) -> str:
    """Fetch /manage snapshot if token is present; otherwise return guidance."""
    token = (token or "").strip()
    if not token:
        return "Management disabled: set `MANAGE_TOKEN` on the onboard app, then enter the same token in the UI."
    try:
        req_headers = {"X-Manage-Token": token}
        req = urllib.request.Request(f"{APP_BASE}/manage", method="GET")
        for k, v in req_headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=5) as r:
            d = __import__("json").loads(r.read().decode())
        # show a compact status string
        if isinstance(d, dict):
            ll = d.get("log_level", "")
            pid = d.get("pid", "")
            return f"Enabled (pid={pid}, log_level={ll})"
        return "Management enabled."
    except Exception:
        return "Management token rejected (forbidden)."


def _fetch_help_msg() -> str:
    """Fetch /help output so UI exposes that endpoint too."""
    try:
        with urllib.request.urlopen(f"{APP_BASE}/help", timeout=2) as r:
            d = __import__("json").loads(r.read().decode())
        msg = d.get("msg", "")
        if not msg:
            return "—"
        import html

        return html.escape(msg).replace("\n", "<br>")
    except Exception:
        return "—"


def _fetch_about_msg() -> str:
    """Fetch /about output so UI exposes that endpoint too."""
    try:
        with urllib.request.urlopen(f"{APP_BASE}/about", timeout=2) as r:
            d = __import__("json").loads(r.read().decode())
        msg = d.get("msg", "")
        if not msg:
            return "—"
        import html

        return html.escape(msg).replace("\n", "<br>")
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
    # Timer on/off: checkbox provides active/inactive, while the time input
    # provides the minutes even when inactive.
    timer_on_active = b"timer_on_enable" in form
    on = (form.get(b"timer_on_minutes") or [b""])[0].decode().strip()
    timer_on_minutes = _parse_timer(on)
    if timer_on_active and timer_on_minutes is None:
        # Avoid sending "active" without a valid time.
        timer_on_active = False
    cmd["timer_on_active"] = timer_on_active
    cmd["timer_on_minutes"] = timer_on_minutes if timer_on_active else timer_on_minutes

    timer_off_active = b"timer_off_enable" in form
    off = (form.get(b"timer_off_minutes") or [b""])[0].decode().strip()
    timer_off_minutes = _parse_timer(off)
    if timer_off_active and timer_off_minutes is None:
        timer_off_active = False
    cmd["timer_off_active"] = timer_off_active
    cmd["timer_off_minutes"] = timer_off_minutes if timer_off_active else timer_off_minutes
    return cmd


def render_template(state: "State", env: str = "—", msg: str = "") -> str:
    from heatpumpirctl import Mode, Fan, State

    def opt(val: str, sel: str) -> str:
        c = " selected" if val == sel else ""
        return f'<option value="{val}"{c}>{val}</option>'

    mode_opts = "".join(opt(m.name, state.mode.name) for m in Mode)
    fan_opts = "".join(opt(f.name, state.fan.name) for f in Fan)

    logs_html = _fetch_logs()
    manage_status = _fetch_manage_status(os.environ.get("MANAGE_TOKEN", ""))
    help_msg_html = _fetch_help_msg()
    about_msg_html = _fetch_about_msg()

    state_summary = state.summary()
    import html
    import json as _json

    now_iso = datetime.now().isoformat()
    state_json = html.escape(_json.dumps(state.to_json(), sort_keys=True))
    state_json_pretty = html.escape(
        _json.dumps(state.to_json(), sort_keys=True, indent=2)
    )
    return (
        TEMPLATE_PATH.read_text()
        .replace("$now_iso", now_iso)
        .replace("$env", env)
        .replace("$state_summary", state_summary)
        .replace("$msg", msg)
        .replace("$logs", logs_html)
        .replace("$help_msg", help_msg_html)
        .replace("$about_msg", about_msg_html)
        .replace("$state_json", state_json)
        .replace("$state_json_pretty", state_json_pretty)
        .replace("$manage_status", manage_status)
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
            "$timer_on_checked", "checked" if state.timer_on_active else ""
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
            "checked" if state.timer_off_active else "",
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
            # Expose /daikin GET: render current UI from latest stored command.
            state = State()
            try:
                with urllib.request.urlopen(f"{APP_BASE}/daikin", timeout=2) as r:
                    d = __import__("json").loads(r.read().decode())
                if isinstance(d, list) and d:
                    latest = d[0].get("command")
                    if isinstance(latest, dict):
                        state = State.from_json(latest)
            except Exception:
                pass

            html = render_template(state, env=_fetch_env())
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
            if b"manage_action" in form:
                manage_action = (form.get(b"manage_action") or [b""])[0].decode().strip().lower()
                manage_level = (form.get(b"manage_level") or [b"INFO"])[0].decode().strip()
                manage_message = (form.get(b"manage_message") or [b""])[0].decode().strip()
                manage_code_raw = (form.get(b"manage_code") or [b"99"])[0].decode().strip()
                manage_token = (form.get(b"manage_token") or [b""])[0].decode().strip() or os.environ.get("MANAGE_TOKEN", "")

                payload: dict = {}
                if manage_action == "inject_log":
                    payload = {"action": "inject_log", "level": manage_level or "INFO", "message": manage_message or "injected-log"}
                elif manage_action == "set_log_level":
                    payload = {"action": "set_log_level", "level": manage_level or "INFO"}
                elif manage_action in ["assert", "raise"]:
                    payload = {"action": manage_action, "message": manage_message or "management failure"}
                elif manage_action == "fatal":
                    try:
                        payload = {"action": "fatal", "code": int(manage_code_raw)}
                    except ValueError:
                        payload = {"action": "fatal", "code": 99}
                elif manage_action == "reset":
                    payload = {"action": "reset"}
                else:
                    payload = {"action": manage_action}

                try:
                    res = _post_manage(payload, token=manage_token)
                    msg = f"Manage OK: {res}"
                except Exception as e:
                    msg = f"Manage error: {e}"
                # Keep state rendering consistent after management actions.
                state = State()
                try:
                    with urllib.request.urlopen(f"{APP_BASE}/daikin", timeout=2) as r:
                        d = __import__("json").loads(r.read().decode())
                    if isinstance(d, list) and d:
                        latest = d[0].get("command")
                        if isinstance(latest, dict):
                            state = State.from_json(latest)
                except Exception:
                    pass

                html = render_template(state, env=_fetch_env(), msg=msg)
            else:
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
                ts = _format_time(d.get("time"))
                if d.get("unchanged"):
                    return f"No IR (unchanged) at {ts}." if ts else "No IR (unchanged)."
                status = "Sent" if d.get("sent") else "Stored"
                return f"{status} at {ts}." if ts else f"{status}."
        except urllib.error.HTTPError as e:
            d = json.loads(e.read().decode()) if e.read() else {}
            return f"Error: {d.get('error', e.code)}"
        except Exception as e:
            return f"Error: {e}"

    def log_message(self, format: str, *args: object) -> None:
        pass


def _post_manage(payload: dict, token: str) -> dict:
    token = (token or "").strip()
    if not token:
        raise RuntimeError("missing manage token")
    headers = {"X-Manage-Token": token}
    # Use same helper to hit POST /manage
    return _post_json(f"{APP_BASE}/manage", payload, headers=headers)


def main() -> None:
    server = HTTPServer(("0.0.0.0", PORT_UI), Handler)
    print(f"UI on http://0.0.0.0:{PORT_UI}")
    server.serve_forever()


if __name__ == "__main__":
    main()
