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
This will take the form of two-legged machine-to-machine OAuth2.
Creds to be provided in environment variables. 
(special sentinel for no creds)
"""

# What that means in practice is that Twoway will GET from the dmz (URL 1)
# and POST it to the Onboard (URL 2).
# Twoway will then POST that the dmz update (URL 3).
#
# repeat, respecting rate limits

import os
import sys
import time

print("twoway line 29")

import requests


print(f"Nothing to see here, yet... {sys.argv}")

assert len(sys.argv) == 4

readfrom = sys.argv[1]
dmz = sys.argv[2]
writeto = sys.argv[3]


def poll_once() -> bool:
    try:
        r1 = requests.get(readfrom)
        print(f"twoway r1 {r1}")
        if r1.status_code != 200: return False
        r2 = requests.post(dmz, r1.text)
        print(f"twoway r2 {r2}")
        if r2.status_cpode != 200: return False
        r3 = requests.post(writeto, r2.text)
        print(f"twoway r3 {r3}")
        if r3.status_code != 200: return False
        return True
    except Exception as e:
        print(f"twoway failed to connect: {e}")
        return False

MAXFAIL = 100
PERIOD_SECS = 5

def poll_forever():
    attempts = MAXFAIL
    slp = PERIOD_SECS
    while attempts > 0:
        print(f"twoway sleep: {slp}, attempts left {attempts}")
        time.sleep(slp) 
        print(f"twoway poll go, attempts left {attempts}")
        ok = poll_once()
        print(f"twoway poll result: {ok}, attempts left {attempts}")
        if ok:
            attempts = MAXFAIL
            slp = PERIOD_SECS
        else:
            attempts -= 1
            slp *= 1.5
    print("twoway too many fail; exit")

print("twoway enter")
if __name__ == "__main__":
    # LOG starting / port
    if os.environ.get("ENV") in ['DOCKERTEST']:
        PERIOD_SECS = 0.1
    poll_forever()
print("twoway exit")
