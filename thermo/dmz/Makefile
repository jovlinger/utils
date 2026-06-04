.PHONY: all clean test test-local test-docker runlocal zone-keys

# Log wrapper: ../../extdeps/run-with-stdout-logged.py. Refresh: make -C ../../extdeps all
RUN_WITH_BIN := $(abspath $(CURDIR)/../../extdeps/run-with-stdout-logged.py)

all: .image

# Plain progress: avoid `docker build -q` (no output until done — looks hung in CI / agent logs).
DOCKER_BUILD_PROGRESS ?= plain

.image: Dockerfile requirements.txt strip_charset_normalizer_so.py .dockerignore start.sh run.sh stage-docker-import.sh $(RUN_WITH_BIN) $(wildcard *.py) $(wildcard test/*.py) $(wildcard test/*.sh) $(wildcard ../ui/*) $(wildcard ../onboard/common/*.py) $(wildcard ../onboard/common/heatpumpirctl/*.py)
	"$(CURDIR)/stage-docker-import.sh"
	docker build --progress=$(DOCKER_BUILD_PROGRESS) -t jovlinger/thermo/dmz .
	@docker image inspect jovlinger/thermo/dmz -f '{{.Id}}' | cut -d: -f2 > .image

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
runlocal: .image
	docker run --rm -it -p 8080:8080 jovlinger/thermo/dmz

# Ed25519 zone machine-auth keypair: private half under ../priv/zone/ (gitignored),
# public half under ../config/zone/ (committed). Onboard keeps priv.pem;
# configure DMZ with ZONE_PUBLIC_KEY or ZONE_PUBLIC_KEY_PATH pointing at pub.pem. See ../KEYS-AND-CERTS.md.
zone-keys:
	@test -f "$(CURDIR)/.venv/bin/python" || test -f "$(CURDIR)/env/bin/python" || { echo "Run ../../create_pipenv.sh thermo/dmz first" >&2; exit 1; }
	@mkdir -p "$(CURDIR)/../priv/zone"
	@mkdir -p "$(CURDIR)/../config/zone"
	@PY=$$([ -f "$(CURDIR)/.venv/bin/python" ] && echo "$(CURDIR)/.venv/bin/python" || echo "$(CURDIR)/env/bin/python"); \
		THERMO_ZONE_PRIVATE_KEYS_DIR="$(CURDIR)/../priv/zone" \
		THERMO_ZONE_PUBLIC_KEYS_DIR="$(CURDIR)/../config/zone" \
		"$$PY" "$(CURDIR)/../test/gen_keys.py"
