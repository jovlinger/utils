"""Serve the thermo UI on port 8080. Plain HTML form POST to app on port 5000."""

import os
import urllib.parse
import urllib.request
import urllib.error
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, List

PORT_UI = int(os.environ.get("UI_PORT", "8080"))
PORT_APP = int(os.environ.get("PORT", "5000"))
APP_BASE = f"http://127.0.0.1:{PORT_APP}"

TEMPLATE_PATH = Path(__file__).parent / "ui_template.html"


def _fetch_env() -> str:
    try:
        with urllib.request.urlopen(f"{APP_BASE}/environment", timeout=2) as r:
            d = __import__("json").loads(r.read().decode())
            t = d.get("temperature_centigrade")
            h = d.get("humidity_percent")
            return f"{t}°C, {h}%" if t is not None and h is not None else "—"
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
    on = (form.get(b"timer_on_minutes") or [b""])[0].decode().strip()
    if on:
        try:
            cmd["timer_on_minutes"] = int(on)
        except ValueError:
            pass
    off = (form.get(b"timer_off_minutes") or [b""])[0].decode().strip()
    if off:
        try:
            cmd["timer_off_minutes"] = int(off)
        except ValueError:
            pass
    return cmd


def render_template(state: "State", env: str = "—", msg: str = "") -> str:
    from heatpumpirctl import Mode, Fan, State

    def opt(val: str, sel: str) -> str:
        c = " selected" if val == sel else ""
        return f'<option value="{val}"{c}>{val}</option>'

    mode_opts = "".join(opt(m.name, state.mode.name) for m in Mode)
    fan_opts = "".join(opt(f.name, state.fan.name) for f in Fan)

    return (
        TEMPLATE_PATH.read_text()
        .replace("$env", env)
        .replace("$msg", msg)
        .replace("$power_checked", "checked" if state.power else "")
        .replace("$swing_checked", "checked" if state.swing else "")
        .replace("$powerful_checked", "checked" if state.powerful else "")
        .replace("$econo_checked", "checked" if state.econo else "")
        .replace("$comfort_checked", "checked" if state.comfort else "")
        .replace("$mode_options", mode_opts)
        .replace("$fan_options", fan_opts)
        .replace("$temp_c", str(state.temp_c))
        .replace(
            "$timer_on",
            str(state.timer_on_minutes) if state.timer_on_minutes is not None else "",
        )
        .replace(
            "$timer_off",
            str(state.timer_off_minutes) if state.timer_off_minutes is not None else "",
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
                return "Sent." if d.get("sent") else "Stored."
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
