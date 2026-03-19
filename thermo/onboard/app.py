"""
Main entry point.

Use as an import for testing. Must use the flask cmd line to start
"""

from anavilib import HTU21D, send_daikin_state
from common import is_test_env, log
from constants import help_msg

from collections import deque
from collections import defaultdict
from datetime import datetime
import logging
import os
import sys
from typing import Any, Dict, Optional, Tuple

from flask import Flask, request

from heatpumpirctl import State
from common import get_log_level, set_log_level

app = Flask(__name__)


def out(msg: str, **kwargs) -> None:
    """Log via common.log (same format as twoway)."""
    log("app", msg, **kwargs)


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
        return {"ok": True, "action": action, "level": level_name, "message": message}, 200

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
        out("management set log level", level=updated)
        return {"ok": True, "action": action, "level": updated}, 200

    if action == "reset":
        global _fake_temp, _fake_humid
        _fake_temp = None
        _fake_humid = None
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


@app.route("/environment", methods=["GET"])
def environment():
    """Return current temperature and humidity from HTU21D sensor (1 decimal)."""
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


DAIKIN_CMDS_MAXLEN = 100
daikin_cmds: deque[tuple[datetime, State, bool]] = deque(maxlen=DAIKIN_CMDS_MAXLEN)


@app.route("/daikin", methods=["GET"])
def get_daikin():
    """Return list of {time, command} for recent daikin commands sent (newest first)."""
    return [
        {"time": ts.isoformat(), "command": s.to_json()}
        for ts, s, _ in reversed(list(daikin_cmds))
    ]


@app.route("/logs", methods=["GET"])
def logs():
    """Return last N lines from LOG_PATH (rolling buffer). JSON {lines} or 404 if no log file."""
    path = os.environ.get("LOG_PATH")
    if not path or not os.path.isfile(path):
        return {"lines": [], "path": path}, 200
    try:
        with open(path) as f:
            lines = f.readlines()
        return {"lines": [ln.rstrip("\n") for ln in lines[-200:]]}
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


@app.route("/daikin", methods=["PUT", "POST"])
def set_daikin():
    """Accept JSON {command: State}, parse to State, store, send via IR. Returns {time, command, sent}."""
    js = request.json or {}
    cmd_obj = js.get("command") if isinstance(js, dict) else js
    if not cmd_obj or not isinstance(cmd_obj, dict):
        out("Empty or invalid command")
        return {"error": "EmptyCmd"}, 400
    try:
        state = State.from_json(cmd_obj)
    except (KeyError, ValueError, TypeError) as e:
        out("Invalid command: %s" % e)
        return {"error": "InvalidCmd", "detail": str(e)}, 400
    ts = datetime.now()
    success = send_daikin_state(state)
    daikin_cmds.append((ts, state, success))
    out("SET_DAIKIN: %s" % state.summary())
    return {"time": ts.isoformat(), "command": state.to_json(), "sent": success}, 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    out("starting", host="0.0.0.0", port=port)
    app.run(host="0.0.0.0", port=port)
