#/bin/bash

# this is INSIDE the container: the driver for the dockerized tests.
# It will connect to the various docker-composed endpoints and call
# them, letting them ping each other.
#
# Environment variables will
# - set up fakes inside the containers (factory methods will choose between real I2C and fake)
# - tell us what hosts to contact (service names in the docker-compose net)

dig dmz
dig onboard

echo "---"

python runtest.py
