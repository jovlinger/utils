#!/bin/bash

# This is the command-line test driver. 
# This composes a docker container and runs it. This is run OUTSIDE the container

# | cat to convince the script that we are not a tty, and to skip the color and redraws
docker compose up --timestamps --abort-on-container-exit --always-recreate-deps --build --exit-code-from  test-driver 2>&1  | cat
