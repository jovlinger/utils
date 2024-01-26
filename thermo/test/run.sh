#/bin/bash

# this is INSIDE the container: the driver for the dockerized tests.
# It will connect to the various docker-composed endpoints and call
# them, letting them ping each other.
#
# Environment variables will
# - set up fakes inside the containers (factory methods will choose between real I2C and fake)
# - tell us what hosts to contact (service names in the docker-compose net)

ping -c2 dmz
ping -c2 onboard

echo "onboard"
wget -O - http://onboard:5000/help

echo "dmz"
wget -O - http://dmz:5000/backends

python runtest.py
