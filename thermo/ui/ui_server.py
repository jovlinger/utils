"""Thermo HTML UI: proxies to the Flask app (onboard or DMZ) via /ui/context and /ui/command."""

from __future__ import annotations

import html
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

# Import heatpumpirctl: Docker /app layout (heatpumpirctl next to ui/) or dev tree (under onboard/).
_THERMO = Path(__file__).resolve().parent.parent
for _p in (_THERMO / "onboard", _THERMO):
    _s = str(_p)
    if _p.is_dir() and _s not in sys.path:
        sys.path.insert(0, _s)

PORT_UI = int(os.environ.get("UI_PORT", "8080"))


def _parse_extra_ui_ports() -> List[int]:
    """Optional comma-separated extra bind ports (e.g. ``80`` for http://pizero/)."""
    raw = os.environ.get("UI_EXTRA_PORTS", "").strip()
    if not raw:
        return []
    ports: List[int] = []
    for part in raw.split(","):
        part = part.strip()
        if part:
            ports.append(int(part))
    return ports


def _all_ui_ports() -> List[int]:
    """Deduplicated list: primary ``UI_PORT`` first, then ``UI_EXTRA_PORTS``."""
    seen: set[int] = set()
    ordered: List[int] = []
    for p in [PORT_UI] + _parse_extra_ui_ports():
        if p not in seen:
            seen.add(p)
            ordered.append(p)
    return ordered


def _parse_timer(s: str) -> Optional[int]:
    """Parse timer: minutes (int) or time-of-day (HH:MM or H:MM). Returns minutes from midnight."""
    s = s.strip()
    if not s:
        return None
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
    h, m = divmod(minutes, 60)
    return f"{h}:{m:02d}"


PORT_APP = int(os.environ.get("PORT", "5000"))
APP_BASE = f"http://127.0.0.1:{PORT_APP}"

TEMPLATE_PATH = Path(__file__).parent / "ui_template.html"


def _ui_backend() -> str:
    """``onboard`` (default) or ``dmz`` — selects log/help/manage behavior."""
    return (os.environ.get("THERMO_UI_BACKEND") or "onboard").strip().lower()


def _format_time(iso: Optional[str]) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S")
    except (ValueError, TypeError):
        return ""


def _format_log_line(line: str) -> str:
    m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z?)\s*(.*)$", line)
    if m:
        return f"<b>{html.escape(m.group(1))}</b> {html.escape(m.group(2))}"
    return html.escape(line)


def _fetch_logs() -> str:
    if _ui_backend() == "dmz":
        try:
            with urllib.request.urlopen(f"{APP_BASE}/debug/logs", timeout=2) as r:
                d = json.loads(r.read().decode())
            logs = d.get("logs", [])
            if not logs:
                return ""
            lines: List[str] = []
            for entry in logs:
                if isinstance(entry, dict):
                    ts = entry.get("ts", "")
                    lines.append(
                        f"{ts} {entry.get('method', '')} {entry.get('path', '')} -> {entry.get('status', '')}"
                    )
                else:
                    lines.append(str(entry))
            return "<br>".join(_format_log_line(ln) for ln in lines)
        except Exception:
            return ""
    try:
        with urllib.request.urlopen(f"{APP_BASE}/logs", timeout=2) as r:
            d = json.loads(r.read().decode())
        lines_raw = d.get("lines", [])
        if not lines_raw:
            return ""
        return "<br>".join(_format_log_line(ln) for ln in lines_raw)
    except Exception:
        return ""


def _fetch_ui_context() -> Optional[Dict[str, Any]]:
    try:
        with urllib.request.urlopen(f"{APP_BASE}/ui/context", timeout=3) as r:
            return json.loads(r.read().decode())
    except Exception:
        return None


def _fetch_manage_status(token: str) -> str:
    if _ui_backend() == "dmz":
        return "Management is not available on the DMZ UI."
    token = (token or "").strip()
    if not token:
        return "Management disabled: set `MANAGE_TOKEN` on the onboard app, then enter the same token in the UI."
    try:
        req = urllib.request.Request(f"{APP_BASE}/manage", method="GET")
        req.add_header("X-Manage-Token", token)
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.loads(r.read().decode())
        if isinstance(d, dict):
            ll = d.get("log_level", "")
            pid = d.get("pid", "")
            return f"Enabled (pid={pid}, log_level={ll})"
        return "Management enabled."
    except Exception:
        return "Management token rejected (forbidden)."


def _fetch_help_msg() -> str:
    if _ui_backend() == "dmz":
        return "—"
    try:
        with urllib.request.urlopen(f"{APP_BASE}/help", timeout=2) as r:
            d = json.loads(r.read().decode())
        msg = d.get("msg", "")
        if not msg:
            return "—"
        return html.escape(msg).replace("\n", "<br>")
    except Exception:
        return "—"


def _fetch_about_msg() -> str:
    if _ui_backend() == "dmz":
        return "—"
    try:
        with urllib.request.urlopen(f"{APP_BASE}/about", timeout=2) as r:
            d = json.loads(r.read().decode())
        msg = d.get("msg", "")
        if not msg:
            return "—"
        return html.escape(msg).replace("\n", "<br>")
    except Exception:
        return "—"


def _form_to_command(form: Dict[bytes, List[bytes]]) -> Dict[str, Any]:
    cmd: Dict[str, Any] = {
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
    timer_on_active = b"timer_on_enable" in form
    on = (form.get(b"timer_on_minutes") or [b""])[0].decode().strip()
    timer_on_minutes = _parse_timer(on)
    if timer_on_active and timer_on_minutes is None:
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


def _env_table_rows(ctx: Mapping[str, Any]) -> str:
    rows: List[str] = []
    for row in ctx.get("environments") or []:
        if not isinstance(row, dict):
            continue
        z = html.escape(str(row.get("zone", "")))
        tc = row.get("temperature_centigrade")
        hm = row.get("humidity_percent")
        ts = html.escape(_format_time(str(row.get("time", "") or "")))
        tc_s = "—" if tc is None else html.escape(str(tc))
        hm_s = "—" if hm is None else html.escape(str(hm))
        rows.append(f"<tr><td>{z}</td><td>{tc_s}</td><td>{hm_s}</td><td>{ts}</td></tr>")
    if not rows:
        rows.append("<tr><td colspan=\"4\">No environment data</td></tr>")
    return "\n".join(rows)


def _zone_options_html(zones: List[str], selected: str) -> str:
    opts: List[str] = []
    for z in zones:
        sel = " selected" if z == selected else ""
        ze = html.escape(z)
        opts.append(f'<option value="{ze}"{sel}>{ze}</option>')
    return "\n".join(opts)


_MANAGE_SECTION_ONBOARD = """
<hr>
<p><b>Management</b></p>
<p>$manage_status</p>
<form method="post" action="/">
  <input type="hidden" name="ui_zone" value="$manage_ui_zone">
  <div class="manage-setting"><label>Token <input type="password" name="manage_token" placeholder="(X-Manage-Token)"></label></div>
  <div class="manage-setting"><label>Action
    <select name="manage_action">
      <option value="inject_log">inject_log</option>
      <option value="set_log_level">set_log_level</option>
      <option value="assert">assert</option>
      <option value="raise">raise</option>
      <option value="fatal">fatal</option>
      <option value="reset">reset</option>
    </select>
  </label></div>
  <div class="manage-setting"><label>Level <input type="text" name="manage_level" value="INFO" size="6"></label></div>
  <div class="manage-setting"><label>Message <input type="text" name="manage_message" value="" size="30"></label></div>
  <div class="manage-setting"><label>Fatal code <input type="text" name="manage_code" value="99" size="4"></label></div>
  <div class="manage-setting"><input type="submit" value="RUN MANAGE"></div>
</form>
"""


def render_template(
    state: Any,
    ctx: Optional[Dict[str, Any]],
    selected_zone: str,
    msg: str = "",
) -> str:
    from heatpumpirctl import Fan, Mode, State

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
    now_iso = datetime.now().isoformat()
    state_json = html.escape(json.dumps(state.to_json(), sort_keys=True))
    state_json_pretty = html.escape(
        json.dumps(state.to_json(), sort_keys=True, indent=2)
    )

    zones: List[str] = []
    if ctx and isinstance(ctx.get("zones"), list):
        zones = [str(z) for z in ctx["zones"] if z is not None]
    if not zones:
        zones = [selected_zone or "default"]
    sel_zone = selected_zone if selected_zone in zones else zones[0]

    env_rows = _env_table_rows(ctx) if ctx else "<tr><td colspan=\"4\">—</td></tr>"
    zone_opts = _zone_options_html(zones, sel_zone)

    if _ui_backend() == "dmz":
        manage_fragment = ""
    else:
        manage_fragment = (
            _MANAGE_SECTION_ONBOARD.replace(
                "$manage_status", html.escape(manage_status)
            ).replace("$manage_ui_zone", html.escape(sel_zone))
        )

    tpl = TEMPLATE_PATH.read_text()
    return (
        tpl.replace("$now_iso", now_iso)
        .replace("$env_table_rows", env_rows)
        .replace("$zone_options", zone_opts)
        .replace("$selected_zone_value", html.escape(sel_zone))
        .replace("$state_summary", state_summary)
        .replace("$msg", html.escape(msg))
        .replace("$logs", logs_html)
        .replace("$help_msg", help_msg_html)
        .replace("$about_msg", about_msg_html)
        .replace("$state_json", state_json)
        .replace("$state_json_pretty", state_json_pretty)
        .replace("$manage_section", manage_fragment)
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
        .replace("$timer_on_checked", "checked" if state.timer_on_active else "")
        .replace(
            "$timer_on",
            (
                _minutes_to_time(state.timer_on_minutes)
                if state.timer_on_minutes is not None
                else ""
            ),
        )
        .replace("$timer_off_checked", "checked" if state.timer_off_active else "")
        .replace(
            "$timer_off",
            (
                _minutes_to_time(state.timer_off_minutes)
                if state.timer_off_minutes is not None
                else ""
            ),
        )
    )


def _state_for_zone(ctx: Optional[Dict[str, Any]], zone: str) -> Any:
    from heatpumpirctl import State

    default = State()
    if not ctx or not isinstance(ctx.get("zone_states"), dict):
        return default
    zs = ctx["zone_states"].get(zone)
    if not isinstance(zs, dict):
        return default
    cmd = zs.get("command")
    if isinstance(cmd, dict):
        try:
            return State.from_json(cmd)
        except (KeyError, ValueError, TypeError):
            return default
    return default


def _parse_zone_from_path(path: str, ctx: Optional[Dict[str, Any]]) -> Optional[str]:
    if "?" not in path:
        return None
    _, qs = path.split("?", 1)
    q = urllib.parse.parse_qs(qs)
    raw = (q.get("zone") or [None])[0]
    if not raw:
        return None
    zones: List[str] = []
    if ctx and isinstance(ctx.get("zones"), list):
        zones = [str(z) for z in ctx["zones"]]
    if zones and raw not in zones:
        return None
    return str(raw)


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            from heatpumpirctl import State

            ctx = _fetch_ui_context()
            zone = _parse_zone_from_path(self.path, ctx) or (
                (ctx.get("zones") or [None])[0] if ctx else None
            )
            if not zone:
                zone = "default"
            state = _state_for_zone(ctx, zone)
            if ctx is None:
                state = State()
                try:
                    with urllib.request.urlopen(f"{APP_BASE}/daikin", timeout=2) as r:
                        d = json.loads(r.read().decode())
                    if isinstance(d, list) and d:
                        latest = d[0].get("command")
                        if isinstance(latest, dict):
                            state = State.from_json(latest)
                except Exception:
                    pass

            html_out = render_template(state, ctx=ctx, selected_zone=zone)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_out.encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:
        if self.path == "/":
            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length else b""
            form = urllib.parse.parse_qs(body, keep_blank_values=True)
            ctx = _fetch_ui_context()
            zones: List[str] = []
            if ctx and isinstance(ctx.get("zones"), list):
                zones = [str(z) for z in ctx["zones"]]

            if b"manage_action" in form and _ui_backend() != "dmz":
                msg = self._post_manage_action(form, ctx)
                ui_zone = (form.get(b"ui_zone") or [b""])[0].decode().strip()
                if not ui_zone or (zones and ui_zone not in zones):
                    ui_zone = zones[0] if zones else "default"
                state = _state_for_zone(ctx, ui_zone)
                html_out = render_template(state, ctx=ctx, selected_zone=ui_zone, msg=msg)
            else:
                ui_zone = (form.get(b"ui_zone") or [b""])[0].decode().strip()
                if not ui_zone or (zones and ui_zone not in zones):
                    ui_zone = zones[0] if zones else "default"
                cmd = _form_to_command(form)
                msg = self._post_ui_command(ui_zone, cmd)
                from heatpumpirctl import State

                state = State.from_json(cmd)
                ctx2 = _fetch_ui_context()
                html_out = render_template(
                    state, ctx=ctx2 or ctx, selected_zone=ui_zone, msg=msg
                )

            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html_out.encode("utf-8"))
            return
        self.send_response(404)
        self.end_headers()

    def _post_ui_command(self, zone: str, cmd: Dict[str, Any]) -> str:
        body_obj = {"zone": zone, "command": cmd}
        body = json.dumps(body_obj).encode("utf-8")
        req = urllib.request.Request(
            f"{APP_BASE}/ui/command",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                d = json.loads(r.read().decode())
            ts = _format_time(str(d.get("time", "") or ""))
            if d.get("unchanged"):
                return f"No IR (unchanged) at {ts}." if ts else "No IR (unchanged)."
            sent = d.get("sent")
            if sent is False:
                return f"Stored at {ts}." if ts else "Stored."
            if sent is True:
                return f"Sent at {ts}." if ts else "Sent."
            return f"OK at {ts}." if ts else "OK."
        except urllib.error.HTTPError as e:
            raw = e.read() or b""
            try:
                err = json.loads(raw.decode())
            except Exception:
                err = {}
            detail = err.get("error", str(e.code))
            return f"Error: {detail}"
        except Exception as e:
            return f"Error: {e}"

    def _post_manage_action(
        self, form: Dict[bytes, List[bytes]], ctx: Optional[Dict[str, Any]]
    ) -> str:
        manage_action = (form.get(b"manage_action") or [b""])[0].decode().strip().lower()
        manage_level = (form.get(b"manage_level") or [b"INFO"])[0].decode().strip()
        manage_message = (form.get(b"manage_message") or [b""])[0].decode().strip()
        manage_code_raw = (form.get(b"manage_code") or [b"99"])[0].decode().strip()
        manage_token = (
            (form.get(b"manage_token") or [b""])[0].decode().strip()
            or os.environ.get("MANAGE_TOKEN", "")
        )

        payload: Dict[str, Any] = {}
        if manage_action == "inject_log":
            payload = {
                "action": "inject_log",
                "level": manage_level or "INFO",
                "message": manage_message or "injected-log",
            }
        elif manage_action == "set_log_level":
            payload = {"action": "set_log_level", "level": manage_level or "INFO"}
        elif manage_action in ("assert", "raise"):
            payload = {
                "action": manage_action,
                "message": manage_message or "management failure",
            }
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
            res = _post_manage_json(payload, token=manage_token)
            return f"Manage OK: {res}"
        except Exception as e:
            return f"Manage error: {e}"

    def log_message(self, format: str, *args: object) -> None:
        pass


def _post_manage_json(payload: dict, token: str) -> dict:
    token = (token or "").strip()
    if not token:
        raise RuntimeError("missing manage token")
    headers = {"X-Manage-Token": token}
    body_bytes = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{APP_BASE}/manage", data=body_bytes, method="POST"
    )
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


def main() -> None:
    if (os.environ.get("THERMO_UI_DISABLE") or "").strip().lower() in (
        "1",
        "true",
        "yes",
    ):
        print(
            "THERMO_UI_DISABLE set: not binding UI ports (use DMZ UI or re-enable later)",
            flush=True,
        )
        return
    ports = _all_ui_ports()
    if len(ports) == 1:
        server = HTTPServer(("0.0.0.0", ports[0]), Handler)
        print(f"UI on http://0.0.0.0:{ports[0]} (backend={_ui_backend()})")
        server.serve_forever()
        return
    for port in ports[1:]:
        s = HTTPServer(("0.0.0.0", port), Handler)
        threading.Thread(
            target=s.serve_forever,
            daemon=True,
            name=f"ui-server-{port}",
        ).start()
        print(f"UI on http://0.0.0.0:{port}")
    first = HTTPServer(("0.0.0.0", ports[0]), Handler)
    print(f"UI on http://0.0.0.0:{ports[0]} (backend={_ui_backend()})")
    first.serve_forever()


if __name__ == "__main__":
    main()
