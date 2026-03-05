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
import os
import sys
from typing import Optional

from flask import Flask, request

from heatpumpirctl import State

app = Flask(__name__)


def out(msg: str, **kwargs) -> None:
    """Log via common.log (same format as twoway)."""
    log("app", msg, **kwargs)


c = defaultdict(lambda: 0)


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
