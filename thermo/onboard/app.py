"""
Main entry point.

Use as an import for testing. Must use the flask cmd line to start
"""

from anavilib import HTU21D
from common import log, LOG_EVERY, LOG_INFO, is_test_env
from constants import help_msg

from datetime import datetime
from collections import defaultdict
import os
import sys

from flask import Flask, request

app = Flask(__name__) 

def _outstderr(msg):
    # For reasons unknown, stdout doesn't get propagated to docker logs / stdout
    print("onboard: "+msg, file=sys.stderr)

out=_outstderr

c = defaultdict(lambda: 0)


@app.route("/<path:path>")
def root(path):
    global c
    log(LOG_INFO, "/", path=path)
    c[path] += 1
    return f"<P>Hello my name is {path} / {c} </P>"


@app.route("/help")
@app.route("/about")
def help():
    return {"msg": help_msg}


@app.route("/environment", methods=["GET"])
def environment():
    htu = HTU21D.singleton()
    temp = htu.temperature_centigrade()
    hum = htu.humidity_percent()
    return {"temperature_centigrade": temp, "humidity_percent": hum}


cmds = {
    "2023-01-10T12:34:56.78": {
        "temp": {"unit": "centigrade", "value": 20.5},
        "mode": "COOL",
        "time": "2023-01-10T12:34:50",
        # .... many more
    }
}


@app.route("/daikin", methods=["GET"])
def get_daikin():
    """Return a dict of {time : command} sent."""
    return cmds


@app.route("/daikin", methods=["PUT", "POST"])  # post not really the right request type
def set_daikin():
    js = request.json
    out(f"SET_DAIKIN: {js}")
    cmd = js.get('command')
    if not cmd:
        out("Empty command")
        return '"EmptyCmd"'
    k = datetime.now().isoformat()
    assert k not in cmds, "why are we asserting?"
    cmds[k] = cmd
    return cmds


if __name__ == "__main__":
    # LOG starting / port
    # log(LOG_EVERY, "use the `flask --app main run` instead")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
