"""
Main entry point.

Use as an import for testing. Must use the flask cmd line to start
"""

from anavilib import HTU21D, send_daikin_state
from common import is_test_env, log
from constants import help_msg

from collections import deque
from datetime import datetime
from collections import defaultdict
import os
import sys

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


@app.route("/environment", methods=["GET"])
def environment():
    """Return current temperature and humidity from HTU21D sensor."""
    htu = HTU21D.singleton()
    temp = htu.temperature_centigrade()
    hum = htu.humidity_percent()
    return {"temperature_centigrade": temp, "humidity_percent": hum}


DAIKIN_CMDS_MAXLEN = 100
daikin_cmds: deque[tuple[datetime, State, bool]] = deque(maxlen=DAIKIN_CMDS_MAXLEN)


@app.route("/daikin", methods=["GET"])
def get_daikin():
    """Return list of {time, command} for recent daikin commands sent (newest first)."""
    return [
        {"time": ts.isoformat(), "command": s.to_json()}
        for ts, s, _ in reversed(list(daikin_cmds))
    ]


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
