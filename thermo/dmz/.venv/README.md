# Project virtualenv marker

This directory marks where the thermo/dmz host virtualenv belongs.
The launcher searches upward for the nearest .venv, venv, or env directory.

Only this README is meant to be committed; generated virtualenv contents stay
local to the machine. The Raspberry Pi DMZ image does not use this host venv;
it installs ARMv6 dependencies inside the Docker image build.
