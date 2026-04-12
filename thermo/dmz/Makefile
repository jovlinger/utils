.PHONY: all clean test test-local test-docker runlocal

# Log wrapper: ../../bin/run-with-stdout-logged.py. Refresh: make -C ../../bin all
RUN_WITH_BIN := $(abspath $(CURDIR)/../../bin/run-with-stdout-logged.py)

all: .image

# Plain progress: avoid `docker build -q` (no output until done — looks hung in CI / agent logs).
DOCKER_BUILD_PROGRESS ?= plain

.image: Dockerfile requirements.txt .dockerignore start.sh run.sh stage-docker-import.sh $(RUN_WITH_BIN) $(wildcard *.py) $(wildcard test/*.py)
	"$(CURDIR)/stage-docker-import.sh"
	docker build --progress=$(DOCKER_BUILD_PROGRESS) -t jovlinger/thermo/dmz .
	@docker image inspect jovlinger/thermo/dmz -f '{{.Id}}' | cut -d: -f2 > .image

clean:
	@[ -f .image ] && docker image rm $$(cat .image) 2>/dev/null || true
	@rm -f .image
	@rm -rf .docker-import

# Host venv, pytest on source (./test/run.sh). No container. Subdirs with their own targets (e.g. smoketest).
test-local:
	./test/run.sh
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
