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
"""

import sys, requests

print(f"Nothing to see here, yet... {sys.argv}")

assert len(sys.argv) == 4

readfrom = sys.argv[1]
dmz = sys.argv[2]
writeto = sys.argv[3]



def poll_once() -> bool:
    r1 = requests.get(readfrom)
    if r1.status_code != 200: return False
    r2 = requests.post(dmz, r1.text)
    if r2.status_cpode != 200: return False
    r3 = requests.post(writeto, r2.text)
    if r3.status_code != 200: return False
    return True

MAXFAIL = 100

def poll_forever():
    attempts = MAXFAIL
    while attempts > 0:
        if poll_once():
            attempts = MAXFAIL
        else:
            attempts -= 1
    time.sleep(1) # control this for test
    print("TOO many fail; exit")
