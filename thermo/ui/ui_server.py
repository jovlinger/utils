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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
            with urllib.request.urlopen(f"{APP_BASE}/ui/diagnostics", timeout=2) as r:
                d = json.loads(r.read().decode())
            cfg = d.get("config") or {}
            uptime = d.get("uptime_seconds")
            summary = (
                f"<span>uptime_s={html.escape(str(uptime))} "
                f"zone_auth={html.escape(str(cfg.get('zone_auth_enforced')))}</span>"
            )
            parts: List[str] = []
            za = d.get("zone_attempts") or []
            if za:
                zlines: List[str] = []
                for entry in za[-40:]:
                    if isinstance(entry, dict):
                        zlines.append(
                            f'{entry.get("ts", "")} {entry.get("outcome", "")} '
                            f'zone={entry.get("zone", "")} '
                            f'{entry.get("path", "")} — {entry.get("detail", "")} '
                            f'ip={entry.get("client_ip", "")} '
                            f'->{entry.get("status_code", "")}'
                        )
                parts.append("<b>Zone POST /sensors (twoway)</b><br>")
                parts.append(
                    "<br>".join(_format_log_line(ln) for ln in zlines)
                )
            logs = d.get("access_log") or []
            if logs:
                lines: List[str] = []
                for entry in logs:
                    if isinstance(entry, dict):
                        ts = entry.get("ts", "")
                        lines.append(
                            f"{ts} {entry.get('method', '')} {entry.get('path', '')} -> {entry.get('status', '')}"
                        )
                    else:
                        lines.append(str(entry))
                parts.append("<br><b>HTTP access (memory)</b><br>")
                parts.append("<br>".join(_format_log_line(ln) for ln in lines))
            body = "<br>".join([summary] + parts) if parts else summary
            return body
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


def _dmz_diagnostics_export_block() -> str:
    """Embedded ``/ui/diagnostics`` JSON for copy-from-browser export (DMZ UI only)."""
    if _ui_backend() != "dmz":
        return ""
    try:
        with urllib.request.urlopen(f"{APP_BASE}/ui/diagnostics", timeout=4) as r:
            raw_json = r.read().decode()
        esc = html.escape(raw_json)
        return (
            "<details><summary><b>Diagnostics JSON</b> "
            "(full export for support — in-memory only on DMZ)</summary>"
            "<p><textarea id=\"thermo-diag-export\" readonly rows=\"14\" cols=\"92\" "
            'style="font-family: monospace; width: 100%; max-width: 52rem;">'
            f"{esc}"
            "</textarea></p>"
            '<p><button type="button" '
            'onclick="var e=document.getElementById(\'thermo-diag-export\');'
            "if(e){e.focus();e.select();document.execCommand('copy');}\">"
            "Copy to clipboard</button></p>"
            "</details>"
        )
    except Exception:
        return "<p><b>Diagnostics JSON</b> unavailable (Flask backend unreachable).</p>"


def _fetch_ui_context_json(
    cookie_header: Optional[str],
) -> tuple[Optional[Dict[str, Any]], int]:
    """
    GET Flask ``/ui/context`` as a programmatic client (``Accept: application/json``).

    Returns ``(payload, http_code)``. ``401`` means OAuth is on and there is no
    session — DMZ ``ui_server`` must redirect the browser to Flask ``/login``.
    ``0`` means transport/parse failure (treat like missing context for onboard).
    """
    req = urllib.request.Request(
        f"{APP_BASE}/ui/context",
        headers={"Accept": "application/json"},
        method="GET",
    )
    ch = (cookie_header or "").strip()
    if ch:
        req.add_header("Cookie", ch)
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            raw = r.read().decode()
            return json.loads(raw), int(r.status)
    except urllib.error.HTTPError as e:
        if e.code == 401:
            return None, 401
        return None, int(e.code)
    except Exception:
        return None, 0


def _fetch_ui_context(cookie_header: Optional[str] = None) -> Optional[Dict[str, Any]]:
    ctx, code = _fetch_ui_context_json(cookie_header)
    if code == 200 and isinstance(ctx, dict):
        return ctx
    return None


def _flask_login_url(handler: BaseHTTPRequestHandler) -> str:
    """Absolute ``/login`` URL on the Flask app (different port than ``ui_server``)."""
    explicit = (os.environ.get("THERMO_UI_LOGIN_ORIGIN") or "").strip().rstrip("/")
    if explicit:
        return f"{explicit}/login"
    host = (handler.headers.get("Host") or "127.0.0.1").strip()
    if ":" in host and not host.startswith("["):
        host_only, tail = host.rsplit(":", 1)
        if tail.isdigit():
            host = host_only
    proto = (
        "https"
        if (handler.headers.get("X-Forwarded-Proto") or "").strip().lower() == "https"
        else "http"
    )
    try:
        pub = int(os.environ.get("THERMO_DMZ_FLASK_PUBLIC_PORT", str(PORT_APP)))
    except ValueError:
        pub = PORT_APP
    return f"{proto}://{host}:{pub}/login"


def _send_flask_login_redirect(handler: BaseHTTPRequestHandler) -> None:
    loc = _flask_login_url(handler)
    handler.send_response(302)
    handler.send_header("Location", loc)
    handler.end_headers()


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
    # Explicit Power on / Power off buttons (see ui_template.html). No power checkbox:
    # absent thermo_action (e.g. Enter in a text field) defaults to power on so other
    # fields still apply predictably.
    action_raw = (form.get(b"thermo_action") or [b""])[0].decode().strip().lower()
    if action_raw == "power_off":
        power = False
    else:
        power = True  # power_on or legacy/implicit submit

    cmd: Dict[str, Any] = {
        "power": power,
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
    cmd["timer_off_minutes"] = (
        timer_off_minutes if timer_off_active else timer_off_minutes
    )
    return cmd


def _deployment_brief(deployment: Any) -> tuple[str, str]:
    """Return (hardware, git) one-line labels for the environment table."""
    if not isinstance(deployment, dict):
        return "—", "—"
    hardware = deployment.get("hardware_profile") or deployment.get("backend") or ""
    git = deployment.get("git_sha_short") or deployment.get("git_sha") or ""
    hw_s = html.escape(str(hardware)) if hardware else "—"
    git_s = html.escape(str(git)) if git else "—"
    return hw_s, git_s


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
        hw_s, git_s = _deployment_brief(row.get("deployment"))
        rows.append(
            f"<tr><td>{z}</td><td>{tc_s}</td><td>{hm_s}</td><td>{ts}</td>"
            f"<td>{hw_s}</td><td>{git_s}</td></tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="6">No environment data</td></tr>')
    return "\n".join(rows)


def _zone_deployment_html(ctx: Optional[Mapping[str, Any]], selected_zone: str) -> str:
    if not ctx:
        return ""
    states = ctx.get("zone_states")
    if not isinstance(states, dict):
        return ""
    zone_state = states.get(selected_zone)
    if not isinstance(zone_state, dict):
        return ""
    deployment = zone_state.get("deployment")
    if not isinstance(deployment, dict) or not deployment:
        return ""
    received = deployment.get("received_dt")
    heading = ""
    if received:
        heading = (
            f"<span>reported {html.escape(str(received))}</span><br>"
        )
    lines: List[str] = []
    for key in sorted(deployment):
        if key == "received_dt":
            continue
        value = deployment.get(key)
        if value is None or value == "":
            continue
        lines.append(
            f"<code>{html.escape(str(key))}</code>: "
            f"{html.escape(str(value))}"
        )
    if not lines:
        return ""
    return heading + "<br>".join(lines)


def _zone_logs_html(ctx: Optional[Mapping[str, Any]], selected_zone: str) -> str:
    if not ctx:
        return ""
    states = ctx.get("zone_states")
    if not isinstance(states, dict):
        return ""
    zone_state = states.get(selected_zone)
    if not isinstance(zone_state, dict):
        return ""
    logs = zone_state.get("logs")
    if not isinstance(logs, dict):
        return ""
    lines = logs.get("lines")
    if not isinstance(lines, list) or not lines:
        return ""
    received = logs.get("received_dt")
    heading = ""
    if received:
        heading = f"<span>last reported {html.escape(str(received))}</span><br>"
    rendered = [
        _format_log_line(str(line))
        for line in lines
        if isinstance(line, str) and line.strip()
    ]
    if not rendered:
        return ""
    return heading + "<br>".join(rendered)


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
    from common.heatpumpirctl import Fan, Mode, State

    def opt(val: str, sel: str) -> str:
        c = " selected" if val == sel else ""
        return f'<option value="{val}"{c}>{val}</option>'

    mode_opts = "".join(opt(m.name, state.mode.name) for m in Mode)
    fan_opts = "".join(opt(f.name, state.fan.name) for f in Fan)

    logs_html = _fetch_logs()
    diag_export_html = _dmz_diagnostics_export_block()
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
    refresh_href = "/?zone=" + urllib.parse.quote(sel_zone, safe="")

    env_rows = _env_table_rows(ctx) if ctx else '<tr><td colspan="6">—</td></tr>'
    zone_opts = _zone_options_html(zones, sel_zone)
    zone_logs_html = _zone_logs_html(ctx, sel_zone)
    zone_deployment_html = _zone_deployment_html(ctx, sel_zone)

    if _ui_backend() == "dmz":
        manage_fragment = ""
    else:
        manage_fragment = _MANAGE_SECTION_ONBOARD.replace(
            "$manage_status", html.escape(manage_status)
        ).replace("$manage_ui_zone", html.escape(sel_zone))

    tpl = TEMPLATE_PATH.read_text()
    return (
        tpl.replace("$now_iso", now_iso)
        .replace("$diagnostics_export_section", diag_export_html)
        .replace("$env_table_rows", env_rows)
        .replace("$zone_options", zone_opts)
        .replace("$selected_zone_value", html.escape(sel_zone))
        .replace("$state_summary", state_summary)
        .replace("$msg", html.escape(msg))
        .replace("$logs", logs_html)
        .replace("$zone_logs", zone_logs_html)
        .replace("$zone_deployment", zone_deployment_html)
        .replace("$help_msg", help_msg_html)
        .replace("$about_msg", about_msg_html)
        .replace("$state_json", state_json)
        .replace("$state_json_pretty", state_json_pretty)
        .replace("$manage_section", manage_fragment)
        .replace("$refresh_href", html.escape(refresh_href))
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
    from common.heatpumpirctl import State

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


# Connection-aborted exceptions we treat as routine: the peer (browser preconnect,
# load balancer health check, port scan, user refresh) closed the TCP connection
# before/while we were reading the request line. Logging full tracebacks for these
# floods onboard-ui.log with noise that has no operational meaning.
_CLIENT_DISCONNECT_ERRORS: tuple = (
    ConnectionResetError,
    ConnectionAbortedError,
    BrokenPipeError,
)


class Handler(BaseHTTPRequestHandler):
    def handle(self) -> None:
        try:
            super().handle()
        except _CLIENT_DISCONNECT_ERRORS as e:
            # One-line debug instead of a stack trace.  No self.log_error: that goes
            # through log_message which we no-op below; use stderr directly so an
            # operator can still see it if log level is raised.
            sys.stderr.write(
                f"ui-server: client disconnected before request complete: "
                f"{type(e).__name__}\n"
            )

    def do_GET(self) -> None:
        if self.path == "/" or self.path.startswith("/?"):
            from common.heatpumpirctl import State

            cookie_header = (self.headers.get("Cookie") or "").strip() or None
            ctx, code = _fetch_ui_context_json(cookie_header)
            if _ui_backend() == "dmz" and code == 401:
                _send_flask_login_redirect(self)
                return

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
            cookie_header = (self.headers.get("Cookie") or "").strip() or None
            ctx, code = _fetch_ui_context_json(cookie_header)
            if _ui_backend() == "dmz" and code == 401:
                _send_flask_login_redirect(self)
                return

            length = int(self.headers.get("Content-Length", "0") or "0")
            body = self.rfile.read(length) if length else b""
            form = urllib.parse.parse_qs(body, keep_blank_values=True)
            zones: List[str] = []
            if ctx and isinstance(ctx.get("zones"), list):
                zones = [str(z) for z in ctx["zones"]]

            if b"manage_action" in form and _ui_backend() != "dmz":
                msg = self._post_manage_action(form, ctx)
                ui_zone = (form.get(b"ui_zone") or [b""])[0].decode().strip()
                if not ui_zone or (zones and ui_zone not in zones):
                    ui_zone = zones[0] if zones else "default"
                state = _state_for_zone(ctx, ui_zone)
                html_out = render_template(
                    state, ctx=ctx, selected_zone=ui_zone, msg=msg
                )
            else:
                ui_zone = (form.get(b"ui_zone") or [b""])[0].decode().strip()
                if not ui_zone or (zones and ui_zone not in zones):
                    ui_zone = zones[0] if zones else "default"
                cmd = _form_to_command(form)
                msg = self._post_ui_command(ui_zone, cmd, cookie_header=cookie_header)
                from common.heatpumpirctl import State

                state = State.from_json(cmd)
                ctx2, _ = _fetch_ui_context_json(cookie_header)
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

    def _post_ui_command(
        self, zone: str, cmd: Dict[str, Any], cookie_header: Optional[str] = None
    ) -> str:
        body_obj = {"zone": zone, "command": cmd}
        body = json.dumps(body_obj).encode("utf-8")
        req = urllib.request.Request(
            f"{APP_BASE}/ui/command",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        ch = (cookie_header or "").strip()
        if ch:
            req.add_header("Cookie", ch)
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
        manage_action = (
            (form.get(b"manage_action") or [b""])[0].decode().strip().lower()
        )
        manage_level = (form.get(b"manage_level") or [b"INFO"])[0].decode().strip()
        manage_message = (form.get(b"manage_message") or [b""])[0].decode().strip()
        manage_code_raw = (form.get(b"manage_code") or [b"99"])[0].decode().strip()
        manage_token = (form.get(b"manage_token") or [b""])[
            0
        ].decode().strip() or os.environ.get("MANAGE_TOKEN", "")

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
    req = urllib.request.Request(f"{APP_BASE}/manage", data=body_bytes, method="POST")
    req.add_header("Content-Type", "application/json")
    for k, v in headers.items():
        req.add_header(k, v)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode())


class _UiHTTPServer(ThreadingHTTPServer):
    """ThreadingHTTPServer that swallows client-disconnect tracebacks.

    ``handle_error`` is the catch-all for any exception that escaped a request
    handler (including before ``handle()`` runs, e.g. inside ``setup()``).  We
    summarize ECONNRESET / ECONNABORTED / EPIPE to a single stderr line and let
    everything else use the default traceback path, so real bugs still surface.
    """

    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, _CLIENT_DISCONNECT_ERRORS):
            sys.stderr.write(
                f"ui-server: client {client_address} disconnected: "
                f"{type(exc).__name__}\n"
            )
            return
        super().handle_error(request, client_address)


def _make_server(port: int) -> _UiHTTPServer:
    return _UiHTTPServer(("0.0.0.0", port), Handler)


def _print_ui_diagnostics_summary() -> bool:
    """Log backend auth flags from ``/ui/diagnostics``. Returns True on success."""
    with urllib.request.urlopen(f"{APP_BASE}/ui/diagnostics", timeout=4) as r:
        d = json.loads(r.read().decode())
    cfg = d.get("config") or {}
    print(
        "ui_server startup (backend /ui/diagnostics): "
        f"zone_auth_enforced={cfg.get('zone_auth_enforced')} "
        f"zone_pubkey_sha256_last4={cfg.get('zone_pubkey_sha256_last4')} "
        f"oauth_enabled={cfg.get('oauth_enabled')} "
        f"google_client_id_last4={cfg.get('google_client_id_last4')} "
        f"flask_secret_key_last4={cfg.get('flask_secret_key_last4')} "
        f"default_dev_secret={cfg.get('flask_secret_is_default_dev')}",
        flush=True,
    )
    return True


def _retry_ui_diagnostics_summary(ports: List[int], attempts: int = 60) -> None:
    """Background retries when Flask was not up at ui_server process start."""
    import time

    for _ in range(attempts):
        time.sleep(1.0)
        try:
            if _print_ui_diagnostics_summary():
                return
        except Exception:
            continue
    print(
        f"ui_server: /ui/diagnostics still unreadable after {attempts}s "
        f"(backend={APP_BASE}); UI may serve without Flask until backend is up",
        flush=True,
    )


def _log_ui_startup_auth(ports: List[int]) -> None:
    """Stderr lines: bind addresses + backend auth flags (from /ui/diagnostics)."""
    print(
        f"ui_server startup: listen 0.0.0.0 ports={ports} backend={APP_BASE} "
        f"THERMO_UI_BACKEND={_ui_backend()}",
        flush=True,
    )
    try:
        _print_ui_diagnostics_summary()
    except Exception as exc:
        print(
            f"ui_server startup: /ui/diagnostics not readable yet ({exc!r}); "
            "retrying in background",
            flush=True,
        )
        threading.Thread(
            target=_retry_ui_diagnostics_summary,
            args=(ports,),
            daemon=True,
            name="ui-diagnostics-retry",
        ).start()


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
    _log_ui_startup_auth(ports)
    if len(ports) == 1:
        server = _make_server(ports[0])
        print(f"UI on http://0.0.0.0:{ports[0]} (backend={_ui_backend()})")
        server.serve_forever()
        return
    for port in ports[1:]:
        s = _make_server(port)
        threading.Thread(
            target=s.serve_forever,
            daemon=True,
            name=f"ui-server-{port}",
        ).start()
        print(f"UI on http://0.0.0.0:{port}")
    first = _make_server(ports[0])
    print(f"UI on http://0.0.0.0:{ports[0]} (backend={_ui_backend()})")
    first.serve_forever()


if __name__ == "__main__":
    main()
