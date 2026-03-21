.PHONY: all clean test runlocal

all: .image

.image: Dockerfile requirements.txt .dockerignore start.sh run.sh stage-docker-import.sh $(RUN_WITH_BIN) $(wildcard *.py) $(wildcard test/*.py)
	"$(CURDIR)/stage-docker-import.sh"
	docker build -q -t jovlinger/thermo/dmz . > .image

clean:
	@[ -f .image ] && docker image rm $$(cat .image) 2>/dev/null || true
	@rm -f .image
	@rm -rf .docker-import

# Sister repo `bin/` next to `utils/` (see thermo/dmz/../../../bin/...)
RUN_WITH_BIN := $(abspath $(CURDIR)/../../../bin/run-with-stdout-logged.py)

# Unit tests inside the built image (stdlib unittest only — no pytest in the image).
test: .image
	docker run --rm --workdir /app --entrypoint python jovlinger/thermo/dmz -m unittest discover -s test -p 'test_*.py' -q

# runlocal: foreground container; API at http://localhost:8080; logs in container
# /var/log/dmz.log (writable layer). Ctrl+C stops the container.
runlocal: .image
	docker run --rm -it -p 8080:8080 jovlinger/thermo/dmz
