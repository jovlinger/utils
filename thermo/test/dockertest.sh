#!/bin/bash

# This is the command-line test driver.
# This composes a docker container and runs it. This is run OUTSIDE the container

# Generate Ed25519 keys for machine auth (twoway -> dmz)
mkdir -p keys
python3 gen_keys.py 2>/dev/null || python gen_keys.py 2>/dev/null || true

# | cat to convince the script that we are not a tty, and to skip the color and redraws
docker compose up --timestamps --abort-on-container-exit --always-recreate-deps --build --exit-code-from  testdriver 2>&1  | cat
