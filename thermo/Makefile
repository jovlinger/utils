# Umbrella targets for the whole thermo/ tree (wired subtrees only — see each Makefile).
#
#   make thermo-envs — refresh host venvs when requirements*.txt change (stamps live under each .venv/).
#   make test        — thermo-envs, then host-only tests in dmz, onboard, test/
#   make all-tests   — test + docker/compose suites (smoketest, dockertest, image builds)
#   make test-local  — alias for test
#   make test-docker — thermo-envs, then docker-only suites (building block for all-tests)
#   make docker-clean — dmz + onboard + test: test containers/staging + prune old image IDs.
#   make docker-all-clean — dmz + onboard + test: docker-clean + all tagged images, stamps, dist/.
#
UTILS_ROOT := $(abspath $(CURDIR)/..)
CREATE_PIPENV := $(UTILS_ROOT)/create_pipenv.sh

DMZ_PIP_PREREQ := $(wildcard dmz/requirements*.txt)
ONBOARD_PIP_PREREQ := $(wildcard onboard/requirements*.txt)
TEST_PIP_PREREQ := $(wildcard test/requirements*.txt)

.PHONY: test all-tests test-local test-docker thermo-envs test-local-only test-docker-only \
	docker-testing-clean docker-old-clean docker-clean docker-all-clean binlinks

thermo-envs: dmz/.venv/.thermo-pip-stamp onboard/.venv/.thermo-pip-stamp test/.venv/.thermo-pip-stamp

# Host venv: only utils/create_pipenv.sh (--sync when requirements changed; creates .venv if missing).
dmz/.venv/.thermo-pip-stamp: $(DMZ_PIP_PREREQ)
	"$(CREATE_PIPENV)" --sync thermo/dmz
	@touch $@

onboard/.venv/.thermo-pip-stamp: $(ONBOARD_PIP_PREREQ)
	"$(CREATE_PIPENV)" --sync thermo/onboard
	@touch $@

test/.venv/.thermo-pip-stamp: $(TEST_PIP_PREREQ)
	"$(CREATE_PIPENV)" --sync thermo/test
	@touch $@

test-local-only:
	$(MAKE) -C dmz test-local
	$(MAKE) -C onboard test-local
	$(MAKE) -C test test-local

test-docker-only:
	$(MAKE) -C dmz test-docker
	$(MAKE) -C onboard test-docker
	$(MAKE) -C test test-docker

test: thermo-envs test-local-only

all-tests: thermo-envs test-local-only test-docker-only

test-local: test

test-docker: thermo-envs test-docker-only

docker-testing-clean:
	$(MAKE) -C dmz docker-testing-clean
	$(MAKE) -C onboard docker-testing-clean
	$(MAKE) -C test docker-testing-clean

docker-old-clean:
	$(MAKE) -C dmz docker-old-clean
	$(MAKE) -C onboard docker-old-clean
	$(MAKE) -C test docker-old-clean

docker-clean: docker-testing-clean docker-old-clean

docker-all-clean:
	$(MAKE) -C dmz docker-all-clean
	$(MAKE) -C onboard docker-all-clean
	$(MAKE) -C test docker-all-clean

binlinks:
	@:
