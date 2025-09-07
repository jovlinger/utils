# this probably wants its own docker container

print("twoway  line 2")

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
> docker cp test-onboard-1:/app/twoway.out -  
"""

import os
import sys
import time
import requests

NOISY=True

def _outfile(msg, force=False):
    if not (NOISY or force):
        return
    # For reasons unknown, stdout doesn't get propagated to docker logs / stdoutx
    with open("twoway.out", "a") as f:
        f.write("twoway: ")
        f.write(msg)
        f.write("\n")
        f.flush()

def _outstderr(msg, force=False):
    if not (NOISY or force):
        return
    # For reasons unknown, stdout doesn't get propagated to docker logs / stdoutx
    print("twoway: "+msg, file=sys.stderr)

out = _outstderr

out(f"Nothing to see here, yet... {sys.argv}")

assert len(sys.argv) == 4

out("out ")

readfrom = sys.argv[1]
dmz = sys.argv[2]
writeto = sys.argv[3]

def post_json(url, body) -> str:
    headers={
        'Content-type':'application/json', 
        'Accept':'application/json'
    }
    r = requests.post(url, json={'commands':{}, 'sensors': {}}, headers=headers)
    assert r.status_code == 200, f"POST {url} -[{r.status_code}]-> {r.text}"
    return r.text


def poll_once() -> bool:
    try:
        res1 = requests.get(readfrom)
        out(f"r1 {readfrom} -> {res1}")
        res2 = post_json(dmz, res1)
        out(f"r2 {dmz} -> {res2}")
        res3 = post_json(writeto, res2)
        out(f"r3 {writeto} -> {res3}")
    except Exception as e:
        out(f"failed to connect: {e}")
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
    if os.environ.get("ENV") in ['DOCKERTEST']:
        PERIOD_SECS = 0.1
    poll_forever()
out("exit")

