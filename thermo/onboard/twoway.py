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


c = 0
def log(x):
    """Open afresh every write"""
    global c
    with open("twoway.log", "a") as f:
        c += 1
        f.write(f"twoway {c}: {x}\n")
        f.flush()

log("twoway line 39")
log("twoway line 40")


log(f"Nothing to see here, yet... {sys.argv}")

assert len(sys.argv) == 4

readfrom = sys.argv[1]
dmz = sys.argv[2]
writeto = sys.argv[3]

def poll_once() -> bool:
    import requests
    try:
        r1 = requests.get(readfrom)
        log(f"twoway r1 {r1}")
        if r1.status_code != 200: return False
        r2 = requests.post(dmz, r1.text)
        log(f"twoway r2 {r2}")
        if r2.status_cpode != 200: return False
        r3 = requests.post(writeto, r2.text)
        log(f"twoway r3 {r3}")
        if r3.status_code != 200: return False
        return True
    except Exception as e:
        log(f"twoway failed to connect: {e}")
        return False

MAXFAIL = 100
PERIOD_SECS = 5

def poll_forever():
    log("twoway poll forever start")
    attempts = MAXFAIL
    slp = PERIOD_SECS
    while attempts > 0:
        log(f"twoway sleep: {slp}, attempts left {attempts}")
        time.sleep(slp) 
        log(f"twoway poll go, attempts left {attempts}")
        ok = poll_once()
        log(f"twoway poll result: {ok}, attempts left {attempts}")
        if ok:
            attempts = MAXFAIL
            slp = PERIOD_SECS
        else:
            attempts -= 1
            slp *= 1.5
    log("twoway too many fail; exit")

log("twoway enter")
if __name__ == "__main__":
    # LOG starting / port
    if os.environ.get("ENV") in ['DOCKERTEST']:
        PERIOD_SECS = 0.1
    poll_forever()
log("twoway exit")
