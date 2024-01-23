#/bin/bash

# this is the driver for the dockerized tests, rather than a local set
# of unittests. we will connect to the various docker-composed
# endpoints and call them, letting them ping each other.
#
# Environment variables will
# - set up fakes inside the containers (factory methods will choose between real I2C and fake)
# - tell us what hosts to contact (service names in the docker-compose net)

# pytest

ping dmz
ping onboard
