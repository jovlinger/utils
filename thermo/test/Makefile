.PHONY: dockertest test test-local test-docker test_e2e clean

# Host pytest (e2e testcases; skips compose-only tests without DMZ_URL=http://dmz:…).
test-local:
	@set -e; \
	if [ -f "$(CURDIR)/../dmz/env/bin/python" ]; then PY="$(CURDIR)/../dmz/env/bin/python"; \
	elif [ -f "$(CURDIR)/env/bin/python" ]; then PY="$(CURDIR)/env/bin/python"; \
	else echo "test-local: need thermo/dmz/env or thermo/test/env (create_pipenv.sh thermo/dmz thermo/test)" >&2; exit 1; \
	fi; \
	cd "$(CURDIR)" && "$$PY" -m pytest -q testcases/

# Builds dmz + onboard images + testdriver, then docker compose (full stack).
test-docker: dockertest

test: test-local test-docker

# Alias: same stack as historical `make test_e2e` name in docs.
test_e2e: test-docker

# Builds thermo/dmz + onboard GHCR-tagged images (../onboard make images) + testdriver, then docker compose up.
# On macOS, default onboard PLATFORM (linux/arm/v7) is often emulated and very slow; use a native Linux arch unless set.
dockertest: .image
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

.image: testcases/*.py *.sh  requirements.txt
	docker build --progress=$(DOCKER_BUILD_PROGRESS) -t jovlinger/thermo/test .
	@docker image inspect jovlinger/thermo/test -f '{{.Id}}' | cut -d: -f2 > .image

clean:
	# if .image; then
	SHA=$(cat .image)
	docker image rm "${SHA}"
	rm .image
	# fi
