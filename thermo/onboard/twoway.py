# this probably wants its own docker container

import os
import sys
import time
import requests

# Same logging as app (configured in common)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import log


def out(msg: str, force: bool = False, **kwargs) -> None:
    """Log via common.log (same format as app)."""
    log("twoway", msg, **kwargs)


usage = """
<name> [-d] URL1 URL2 URL3

Options:

-d deamon mode: if present, fork and return

--

A small standalone binary that:

1. does a GET from URL 1
2. takes that and POSTs it to URL 2.
3. takes the response from URL 2 (if 200)
4. and POSTs it to URL 3.
5. take a breath, and repeat.

There will be rudimentary authorization for URL 2. None for URL 1 or 3. TBD

> make dockertest
"""

out("start", argv=sys.argv)

assert len(sys.argv) == 4

out("out ")

readfrom = sys.argv[1]
dmz = sys.argv[2]
writeto = sys.argv[3]


def post_json(url: str, body: dict) -> str:
    headers = {"Content-type": "application/json", "Accept": "application/json"}
    r = requests.post(url, json={"commands": {}, "sensors": {}}, headers=headers)
    assert r.status_code == 200, f"POST {url} -[{r.status_code}]-> {r.text}"
    return r.text


def poll_once() -> bool:
    try:
        res1 = requests.get(readfrom)
        out("r1 get", url=readfrom, status=res1.status_code)
        res2 = post_json(dmz, res1.json() if res1.ok else {})
        out("r2 post dmz", url=dmz)
        res3 = post_json(writeto, res2 if isinstance(res2, dict) else {})
        out("r3 post writeto", url=writeto)
    except Exception as e:
        out("failed", error=str(e))
        return False
    return True


MAXFAIL = 100
PERIOD_SECS = 5


def poll_forever():
    out("twoway poll forever start")
    attempts = MAXFAIL
    slp = PERIOD_SECS
    while attempts > 0:
        out(f"sleep: {slp}, attempts left {attempts}")
        time.sleep(slp)
        ok = poll_once()
        if ok:
            attempts = MAXFAIL
            slp = PERIOD_SECS
        else:
            attempts -= 1
            slp *= 1.5
    out("too many fail; exit")


out("enter")
if __name__ == "__main__":
    # LOG starting / port
    if os.environ.get("ENV") in ["DOCKERTEST"]:
        PERIOD_SECS = 0.1
    poll_forever()
out("exit")
