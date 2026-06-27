.PHONY: all clean test test-local test-docker runlocal zone-keys assert_docker_up image-armv6 \
	docker-testing-clean docker-old-clean docker-clean docker-all-clean

# Log wrapper: ../../extdeps/run-with-stdout-logged.py. Refresh: make -C ../../extdeps all
RUN_WITH_BIN := $(abspath $(CURDIR)/../../extdeps/run-with-stdout-logged.py)
UTILS_ROOT := $(abspath $(CURDIR)/../..)

include $(abspath $(CURDIR)/../../lib/assert-docker.mk)

# docker-testing-clean: smoketest / viability containers, .docker-import staging.
# docker-old-clean: keep newest jovlinger/thermo/dmz plus protected :armv6; drop other stale IDs.
# docker-all-clean: also untagged/test tags, .image, dist/dmz.img (armv6 stays protected).
DOCKER_CLEAN_REPOS := jovlinger/thermo/dmz
DOCKER_CLEAN_PROTECTED_IMAGE_REFS := jovlinger/thermo/dmz:armv6
DOCKER_CLEAN_CONTAINER_NAMES := dmz-smoketest
DOCKER_CLEAN_CONTAINER_NAME_PREFIXES := dmz-startup-viability-
DOCKER_CLEAN_MARKERS := .image
DOCKER_CLEAN_STAGING_DIRS := .docker-import
DOCKER_CLEAN_OUTPUT_DIRS := dist
include $(UTILS_ROOT)/lib/docker-clean.mk

all: .image

# Plain progress: avoid `docker build -q` (no output until done — looks hung in CI / agent logs).
DOCKER_BUILD_PROGRESS ?= plain

.image: assert_docker_up Dockerfile requirements.txt strip_charset_normalizer_so.py .dockerignore start.sh run.sh stage-docker-import.sh $(RUN_WITH_BIN) $(wildcard *.py) $(wildcard test/*.py) $(wildcard test/*.sh) $(wildcard ../ui/*) $(wildcard ../onboard/common/*.py) $(wildcard ../onboard/common/heatpumpirctl/*.py)
	"$(CURDIR)/stage-docker-import.sh"
	docker build --progress=$(DOCKER_BUILD_PROGRESS) -t jovlinger/thermo/dmz .
	@docker image inspect jovlinger/thermo/dmz -f '{{.Id}}' | cut -d: -f2 > .image

# Pi 1B production image (linux/arm/v6). Same Dockerfile as .image; build-and-write.sh uses this tag.
DMZ_IMAGE_ARMV6 := jovlinger/thermo/dmz:armv6
DMZ_DOCKER_SRCS := Dockerfile requirements.txt strip_charset_normalizer_so.py .dockerignore start.sh run.sh stage-docker-import.sh $(RUN_WITH_BIN) $(wildcard *.py) $(wildcard test/*.py) $(wildcard test/*.sh) $(wildcard ../ui/*) $(wildcard ../onboard/common/*.py) $(wildcard ../onboard/common/heatpumpirctl/*.py)

image-armv6: assert_docker_up $(DMZ_DOCKER_SRCS)
	"$(CURDIR)/stage-docker-import.sh"
	docker buildx build --progress=$(DOCKER_BUILD_PROGRESS) --platform linux/arm/v6 \
		-t $(DMZ_IMAGE_ARMV6) --load -f "$(CURDIR)/Dockerfile" "$(CURDIR)"

clean:
	@[ -f .image ] && docker image rm $$(cat .image) 2>/dev/null || true
	@rm -f .image
	@rm -rf .docker-import

# Host venv, pytest on source (./test/run.sh). No container. Subdirs with their own targets (e.g. smoketest).
test-local:
	./test/run.sh test/ ../ui/tests/
	$(MAKE) -C smoketest test-local

# In-image pytest + smoketest (Docker + live HTTP pytest under smoketest/).
test-docker: .image
	docker run --rm --workdir /app --entrypoint python jovlinger/thermo/dmz -m pytest -q test
	$(MAKE) -C smoketest test-docker

test: test-local test-docker

# runlocal: foreground container; API at http://localhost:8080; logs in container
# /var/log/dmz.log (writable layer). Ctrl+C stops the container.
runlocal: assert_docker_up .image
	docker run --rm -it -p 8080:8080 jovlinger/thermo/dmz

# Ed25519 zone machine-auth keypair: private half under ../priv/zone/ (gitignored),
# public half under ../config/zone/ (committed). Onboard keeps priv.pem;
# configure DMZ with ZONE_PUBLIC_KEY or ZONE_PUBLIC_KEY_PATH pointing at pub.pem. See ../KEYS-AND-CERTS.md.
zone-keys:
	@mkdir -p "$(CURDIR)/../priv/zone"
	@mkdir -p "$(CURDIR)/../config/zone"
	@. "$(CURDIR)/../../lib/venv-resolve.sh"; \
		resolve_utils_venv "$(CURDIR)" "$(CURDIR)/../.." >/dev/null; \
		PY="$$(utils_venv_python_bin "$$VENV_DIR")"; \
		THERMO_ZONE_PRIVATE_KEYS_DIR="$(CURDIR)/../priv/zone" \
		THERMO_ZONE_PUBLIC_KEYS_DIR="$(CURDIR)/../config/zone" \
		"$$PY" "$(CURDIR)/../test/gen_keys.py"
