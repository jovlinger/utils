# Shared Docker daemon check for Make targets that invoke docker.
# Include from any Makefile under utils/:
#   include $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../../../lib/assert-docker.mk)
# (adjust the ../ depth to reach utils/lib from your Makefile directory)

.PHONY: assert_docker_up
assert_docker_up:
	@command -v docker >/dev/null 2>&1 || { echo "assert_docker_up: docker not found in PATH" >&2; exit 127; }
	@docker info >/dev/null 2>&1 || { echo "assert_docker_up: docker daemon not reachable (is Docker running?)" >&2; exit 1; }
