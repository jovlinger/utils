# DMZ smoketest: Dockerized DMZ + host venv pytest against live HTTP (see README.md).
#
.PHONY: test test-local test-docker

# No in-repo pytest without the running container; host-only checks live under ../test/.
test-local:
	@echo "dmz/smoketest: no test-local target (smoketest is test-docker: container + pytest)."
	@true

test-docker:
	./run.sh

test: test-local test-docker
