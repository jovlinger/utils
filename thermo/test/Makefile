.PHONY: dockertest test test-local test-docker test_e2e clean assert_docker_up \
	docker-testing-clean docker-old-clean docker-clean docker-all-clean

include $(abspath $(CURDIR)/../../lib/assert-docker.mk)

UTILS_ROOT := $(abspath $(CURDIR)/../..)

# docker-testing-clean: compose stack, gen_keys output, dockertest log.
# docker-all-clean: also jovlinger/thermo/test image and .image stamp.
DOCKER_CLEAN_REPOS := jovlinger/thermo/test
DOCKER_CLEAN_MARKERS := .image
DOCKER_CLEAN_STAGING_DIRS := keys
DOCKER_CLEAN_TEST_FILES := .dockertest-last.log
DOCKER_CLEAN_COMPOSE_DIRS := .
include $(UTILS_ROOT)/lib/docker-clean.mk

# Host pytest (e2e testcases; skips compose-only tests without DMZ_URL=http://dmz:…).
# Sources THERMO_ENV_FILE via thermo/config/source-thermo-env.sh (default: config/test.env.sample).
THERMO_ROOT := $(abspath $(CURDIR)/..)
THERMO_ENV_FILE ?= config/test.env.sample

test-local:
	@set -e; \
	export THERMO_ROOT="$(THERMO_ROOT)"; \
	export THERMO_ENV_FILE="$(THERMO_ENV_FILE)"; \
	. "$(THERMO_ROOT)/config/source-thermo-env.sh"; \
	. "$(THERMO_ROOT)/../lib/venv-resolve.sh"; \
	resolve_utils_venv "$(CURDIR)" "$(THERMO_ROOT)/.." >/dev/null; \
	PY="$$(utils_venv_python_bin "$$VENV_DIR")"; \
	cd "$(CURDIR)" && "$$PY" -m pytest -q testcases/

# Builds dmz + onboard images + testdriver, then docker compose (full stack).
test-docker: dockertest

test: test-local test-docker

# Alias: same stack as historical `make test_e2e` name in docs.
test_e2e: test-docker

# Builds thermo/dmz + onboard GHCR-tagged images (../onboard make images) + testdriver, then docker compose up.
# IMPORTANT: this is the *test* path on a developer host. We override PLATFORM to host-native here so the
# QEMU-emulated armhf/armv6 build does not take forever. Production images for the Pis are built elsewhere:
#   - DMZ Pi 1B (armv6): thermo/dmz/build-and-write.sh (Alpine RPi armhf SD image)
#   - Onboard Pi Zero 2 W (armv7 default / arm64): thermo/onboard/Makefile `make images` with PLATFORM
# Do NOT remove the Darwin-arm64 → linux/arm64 mapping below — it only applies to the test stack.
dockertest: assert_docker_up .image
	@set -e; \
	case "$$(uname -s)-$$(uname -m)" in \
	Darwin-arm64) export PLATFORM="$${PLATFORM:-linux/arm64}";; \
	Darwin-x86_64) export PLATFORM="$${PLATFORM:-linux/amd64}";; \
	esac; \
	export DOCKER_BUILDKIT="$${DOCKER_BUILDKIT:-1}"; \
	echo "dockertest: PLATFORM=$${PLATFORM:-<Makefile default>}"; \
	$(MAKE) -C ../onboard images; \
	$(MAKE) -C ../dmz .image; \
	./dockertest.sh

# Plain progress: avoid `docker build -q` (silent until complete; dockertest looked “stuck” after onboard builds).
DOCKER_BUILD_PROGRESS ?= plain

.image: assert_docker_up testcases/*.py *.sh  requirements.txt
	docker build --progress=$(DOCKER_BUILD_PROGRESS) -t jovlinger/thermo/test .
	@docker image inspect jovlinger/thermo/test -f '{{.Id}}' | cut -d: -f2 > .image

clean:
	# if .image; then
	SHA=$(cat .image)
	docker image rm "${SHA}"
	rm .image
	# fi
