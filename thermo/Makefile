# Umbrella targets for the whole thermo/ tree (wired subtrees only — see each Makefile).
#
#   make thermo-envs — refresh host venvs when requirements*.txt change (stamps live under each .venv/).
#   make test-local  — thermo-envs, then each component’s host-only tests (test/ sources THERMO_ENV_FILE, default config/test.env.sample).
#   make test-docker — thermo-envs (for smoketest / gen_keys), then Docker / compose suites.
#   make test        — thermo-envs once, then test-local-only + test-docker-only.
#   make docker-clean — dmz + onboard + test: test containers/staging + prune old image IDs.
#   make docker-all-clean — dmz + onboard + test: docker-clean + all tagged images, stamps, dist/.
#
UTILS_ROOT := $(abspath $(CURDIR)/..)
CREATE_PIPENV := $(UTILS_ROOT)/create_pipenv.sh

DMZ_PIP_PREREQ := $(wildcard dmz/requirements*.txt)
ONBOARD_PIP_PREREQ := $(wildcard onboard/requirements*.txt)
TEST_PIP_PREREQ := $(wildcard test/requirements*.txt)

.PHONY: test test-local test-docker thermo-envs test-local-only test-docker-only \
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

test-local: thermo-envs test-local-only

test-docker: thermo-envs test-docker-only

test: thermo-envs
	$(MAKE) test-local-only
	$(MAKE) test-docker-only

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
