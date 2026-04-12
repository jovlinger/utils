"""
Main entry point.

Use as an import for testing. Must use the flask cmd line to start
"""

from anavilib import HTU21D, send_daikin_state
from common import is_test_env, log, log_debug
from constants import help_msg

from collections import deque
from collections import defaultdict
from datetime import datetime
import json
import logging
import os
from typing import Any, Dict, FrozenSet, Optional, Tuple

from flask import Flask, request

from heatpumpirctl import State
from common import get_log_level, set_log_level

app = Flask(__name__)


def out(msg: str, **kwargs) -> None:
    """Log via common.log (same format as twoway)."""
    log("app", msg, **kwargs)


def dbg(msg: str, **kwargs) -> None:
    """Log at DEBUG (same kwargs style as info)."""
    log_debug("app", msg, **kwargs)


c = defaultdict(lambda: 0)

MANAGE_TOKEN_ENVVAR = "MANAGE_TOKEN"


def _manage_auth_ok() -> bool:
    """Allow management operations only with a matching token."""
    token = os.environ.get(MANAGE_TOKEN_ENVVAR, "")
    presented = request.headers.get("X-Manage-Token", "")
    return bool(token and presented and token == presented)


def _state_snapshot() -> Dict[str, Any]:
    """Return an internal state snapshot for forensics and testing."""
    return {
        "time": datetime.now().isoformat(),
        "pid": os.getpid(),
        "log_level": get_log_level(),
        "log_path": os.environ.get("LOG_PATH"),
        "fake_sensor": {
            "temperature_centigrade": _round1(_fake_temp),
            "humidity_percent": _round1(_fake_humid),
        },
        "daikin_queue_size": len(daikin_cmds),
        "daikin_queue_capacity": DAIKIN_CMDS_MAXLEN,
        "env": {
            "ENV": os.environ.get("ENV"),
            "PORT": os.environ.get("PORT"),
            "DMZ_URL": os.environ.get("DMZ_URL"),
        },
    }


def _parse_exit_code(value: Any) -> int:
    code = int(value)
    if code < 1 or code > 255:
        raise ValueError("code must be in [1,255]")
    return code


def _management_action(payload: Dict[str, Any]) -> Tuple[Dict[str, Any], int]:
    action = str(payload.get("action", "")).strip().lower()
    if not action:
        return {"error": "missing action"}, 400

    if action == "inject_log":
        level_name = str(payload.get("level", "INFO")).upper().strip()
        message = str(payload.get("message", "injected-log"))
        logger = logging.getLogger("onboard")
        level = getattr(logging, level_name, None)
        if not isinstance(level, int):
            return {"error": "invalid level"}, 400
        logger.log(level, "manage: injected log message=%r", message)
        return {
            "ok": True,
            "action": action,
            "level": level_name,
            "message": message,
        }, 200

    if action == "assert":
        msg = str(payload.get("message", "management assertion failure"))
        out("management assert", message=msg)
        raise AssertionError(msg)

    if action == "raise":
        msg = str(payload.get("message", "management runtime failure"))
        out("management raise", message=msg)
        raise RuntimeError(msg)

    if action == "fatal":
        code = _parse_exit_code(payload.get("code", 99))
        out("management fatal exit", code=code)
        os._exit(code)

    if action == "set_log_level":
        level_name = str(payload.get("level", "")).strip()
        updated = set_log_level(level_name)
        if not updated:
            return {"error": "invalid level"}, 400
        out("management set log level", log_level=updated)
        return {"ok": True, "action": action, "level": updated}, 200

    if action == "reset":
        global _fake_temp, _fake_humid, _last_daikin_ir_fingerprint, _last_applied_state
        _fake_temp = None
        _fake_humid = None
        _last_daikin_ir_fingerprint = None
        _last_applied_state = None
        daikin_cmds.clear()
        out("management reset state")
        return {"ok": True, "action": action}, 200

    return {"error": "unknown action"}, 400


@app.route("/<path:path>")
def root(path):
    """This is just a test route to make sure the server is running."""
    global c
    out("request", path=path)
    c[path] += 1
    return f"<P>Hello my name is {path} / {c} </P>"


@app.route("/help")
@app.route("/about")
def help():
    return {"msg": help_msg}


# Test override: when set, /environment returns these instead of sensor
_fake_temp: Optional[float] = None
_fake_humid: Optional[float] = None


def _round1(x: Optional[float]) -> Optional[float]:
    return round(x, 1) if x is not None else None


def _environment_dict() -> Dict[str, Any]:
    """Current environment payload (same shape as GET /environment)."""
    global _fake_temp, _fake_humid
    ts = datetime.now()
    if _fake_temp is not None and _fake_humid is not None:
        return {
            "temperature_centigrade": _round1(_fake_temp),
            "humidity_percent": _round1(_fake_humid),
            "time": ts.isoformat(),
        }
    try:
        htu = HTU21D.singleton()
        temp = htu.temperature_centigrade()
        hum = htu.humidity_percent()
        return {
            "temperature_centigrade": _round1(temp),
            "humidity_percent": _round1(hum),
            "time": ts.isoformat(),
        }
    except Exception as e:
        out("environment", error=str(e))
        return {
            "temperature_centigrade": None,
            "humidity_percent": None,
            "time": ts.isoformat(),
        }


@app.route("/environment", methods=["GET"])
def environment():
    """Return current temperature and humidity from HTU21D sensor (1 decimal)."""
    return _environment_dict()


@app.route("/test/inject_readings", methods=["POST"])
def test_inject_readings():
    """Set fake sensor values for testing. Body: {temp_centigrade, humid_percent}."""
    global _fake_temp, _fake_humid
    if not is_test_env():
        return {"error": "only in test env"}, 403
    js = request.json or {}
    _fake_temp = js.get("temp_centigrade")
    _fake_humid = js.get("humid_percent")
    return {"temp_centigrade": _fake_temp, "humid_percent": _fake_humid}


@app.route("/test/reset", methods=["POST"])
def test_reset():
    """Clear in-memory command history and state for test isolation."""
    global _last_daikin_ir_fingerprint, _last_applied_state
    if not is_test_env():
        return {"error": "only in test env"}, 403
    daikin_cmds.clear()
    _last_daikin_ir_fingerprint = None
    _last_applied_state = None
    return {"ok": True}


DAIKIN_CMDS_MAXLEN = 100
daikin_cmds: deque[tuple[datetime, State, bool]] = deque(maxlen=DAIKIN_CMDS_MAXLEN)

# Keys understood by heatpumpirctl.State.from_json (canonical lowercase).
_STATE_FROM_JSON_KEYS: FrozenSet[str] = frozenset(
    {
        "power",
        "mode",
        "temp_c",
        "half_c",
        "fan",
        "swing",
        "powerful",
        "econo",
        "comfort",
        "timer_on_minutes",
        "timer_off_minutes",
        "timer_on_active",
        "timer_off_active",
    }
)


def _command_dict_for_state(cmd: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build the dict passed to State.from_json from a raw zone command.

    DMZ/twoway may carry noise (lolidk, created_dt, last_access_dt). CLI callers
    may use any casing (FAN=F1). Only keys in _STATE_FROM_JSON_KEYS are kept,
    renamed to lowercase.
    """
    out: Dict[str, Any] = {}
    for key, val in cmd.items():
        canon = str(key).lower()
        if canon in _STATE_FROM_JSON_KEYS:
            out[canon] = val
    return out


# Last IR payload successfully sent (JSON fingerprint); identical State skips send_daikin_state.
_last_daikin_ir_fingerprint: Optional[str] = None

# Last State applied on /daikin (UI or twoway); used to merge partial DMZ commands from twoway.
_last_applied_state: Optional[State] = None


def _daikin_state_fingerprint(state: State) -> str:
    """Stable string for IR-relevant fields (no wall-clock in State)."""
    return json.dumps(state.to_json(), sort_keys=True)


@app.route("/daikin", methods=["GET"])
def get_daikin():
    """Return list of {time, command} for recent daikin commands sent (newest first)."""
    return [
        {"time": ts.isoformat(), "command": s.to_json()}
        for ts, s, _ in reversed(list(daikin_cmds))
    ]


@app.route("/logs", methods=["GET"])
def logs():
    """Return last N lines from LOG_PATH (rolling buffer). JSON {lines}, newest first."""
    path = os.environ.get("LOG_PATH")
    if not path or not os.path.isfile(path):
        return {"lines": [], "path": path}, 200
    try:
        with open(path) as f:
            lines = f.readlines()
        tail = [ln.rstrip("\n") for ln in lines[-200:]]
        return {"lines": list(reversed(tail))}
    except OSError:
        return {"lines": []}, 200


@app.route("/manage", methods=["GET"])
def manage_get():
    """Return internal state for diagnostics."""
    if not _manage_auth_ok():
        return {"error": "forbidden"}, 403
    return _state_snapshot(), 200


@app.route("/manage", methods=["POST"])
def manage_post():
    """Execute one management action for fault-injection or runtime tuning."""
    if not _manage_auth_ok():
        return {"error": "forbidden"}, 403
    js = request.json or {}
    if not isinstance(js, dict):
        return {"error": "json object required"}, 400
    return _management_action(js)


def _daikin_response_payload(ts_iso: str, state: State, **extra: Any) -> Dict[str, Any]:
    """JSON for successful /daikin responses (authoritative command + environment)."""
    pl: Dict[str, Any] = {
        "time": ts_iso,
        "command": state.to_json(),
        "environment": _environment_dict(),
    }
    pl.update(extra)
    return pl


@app.route("/daikin", methods=["PUT", "POST"])
def set_daikin():
    """Accept a zone state or bare command dict, convert to State, send IR if changed.

    Twoway posts the raw DMZ zone state ({command, sensors}). Partial DMZ commands are
    merged onto the last applied onboard State so the UI is not overwritten by stale
    narrow keys (e.g. only fan). Direct UI posts typically send {command} without sensors
    and replace behavior as before. Command keys are normalized via _command_dict_for_state.

    Successful responses include ``command`` (authoritative State JSON) and
    ``environment`` (same as GET /environment) so twoway can push command back to DMZ.

    Repeated identical commands do not re-send IR. Returns {time, command, environment, sent}.
    """
    global _last_daikin_ir_fingerprint, _last_applied_state
    js = request.json or {}
    dbg("set_daikin", js=js)
    cmd_obj = js.get("command") if isinstance(js, dict) else js
    if cmd_obj is None:
        dbg("no command in zone state; skipping /daikin")
        return {
            "sent": False,
            "reason": "no command",
            "environment": _environment_dict(),
        }, 200
    if not isinstance(cmd_obj, dict):
        out("Invalid command: expected dict, got %s" % type(cmd_obj).__name__)
        return {"error": "EmptyCmd"}, 400
    merged = _command_dict_for_state(cmd_obj)
    if not merged:
        dbg(
            "set_daikin no state fields in command",
            keys=list(cmd_obj.keys()),
        )
        return {
            "sent": False,
            "reason": "no state fields in command",
            "environment": _environment_dict(),
        }, 200

    from_dmz_twoway = isinstance(js, dict) and "sensors" in js
    try:
        if from_dmz_twoway and _last_applied_state is not None:
            base = _last_applied_state.to_json()
            merged_for_state = {**base, **merged}
            dbg(
                "set_daikin merge twoway command into last state",
                merged_incoming=merged,
            )
            state = State.from_json(merged_for_state)
        else:
            dbg("set_daikin state preconvert", merged=merged)
            state = State.from_json(merged)
        dbg("set_daikin state", state=state)
    except (KeyError, ValueError, TypeError) as e:
        out("Invalid command: %s" % e)
        return {"error": "InvalidCmd", "detail": str(e)}, 400

    ts = datetime.now()
    ts_iso = ts.isoformat()
    fp = _daikin_state_fingerprint(state)
    if _last_daikin_ir_fingerprint is not None and fp == _last_daikin_ir_fingerprint:
        out("SET_DAIKIN unchanged (no IR): %s" % state.summary())
        _last_applied_state = state
        return _daikin_response_payload(ts_iso, state, sent=False, unchanged=True), 200
    success = send_daikin_state(state)
    if success:
        _last_daikin_ir_fingerprint = fp
    _last_applied_state = state
    daikin_cmds.append((ts, state, success))
    out("SET_DAIKIN: %s" % state.summary())
    return _daikin_response_payload(ts_iso, state, sent=success), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    out("starting", host="0.0.0.0", port=port)
    app.run(host="0.0.0.0", port=port)
