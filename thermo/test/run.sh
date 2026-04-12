#!/bin/bash

# this is INSIDE the container: the driver for the dockerized tests.
# It will connect to the various docker-composed endpoints and call
# them, letting them ping each other.
#
# Environment variables will
# - set up fakes inside the containers (factory methods will choose between real I2C and fake)
# - tell us what hosts to contact (service names in the docker-compose net)

# HTTP readiness (ICMP is often blocked; ping can look “hung” on some Docker setups).
echo "waiting for dmz and onboard HTTP..."
for i in $(seq 1 90); do
  if curl -sf --max-time 2 "http://dmz:8080/zones" >/dev/null; then
    break
  fi
  sleep 1
done
curl -sf --max-time 5 "http://dmz:8080/zones" >/dev/null
curl -sf --max-time 5 "http://onboard:5000/help" >/dev/null

echo "this is the run.sh script, about to invoke pytest"

# -s un-suppresses output to stdout
pytest -s testcases/
