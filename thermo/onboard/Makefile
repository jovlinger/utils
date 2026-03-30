# Build and push thermo-onboard-app and thermo-onboard-twoway to GHCR.
# Pi Zero 2 W: arm64 or armhf. Requires CR_PAT for push.
.PHONY: all build push clean test ci

IMAGE_APP := ghcr.io/jovlinger/thermo-onboard-app
IMAGE_TWOWAY := ghcr.io/jovlinger/thermo-onboard-twoway
TAG ?= latest
# Pi Zero 2 W with 32-bit OS (armhf); use linux/arm64 for 64-bit OS
PLATFORM ?= linux/arm/v7

RUN_WITH_BIN := $(abspath $(CURDIR)/../../../bin/run-with-stdout-logged.py)

DOCKERFILES := Dockerfile.onboard Dockerfile.twoway
ENTRYPOINTS := docker-entrypoint-onboard.sh docker-entrypoint-twoway.sh
PY_SRC := $(wildcard *.py) $(wildcard heatpumpirctl/*.py)

all: build

build: .image.app .image.twoway

.image.app: Dockerfile.onboard requirements.txt stage-docker-import.sh $(RUN_WITH_BIN) $(DOCKERFILES) $(ENTRYPOINTS) $(PY_SRC) ui_server.py ui_template.html
	"$(CURDIR)/stage-docker-import.sh"
	docker buildx build -q --platform $(PLATFORM) -f Dockerfile.onboard -t $(IMAGE_APP):$(TAG) --load .
	@docker image inspect $(IMAGE_APP):$(TAG) -f '{{.Id}}' | cut -d: -f2 > .image.app

.image.twoway: Dockerfile.twoway requirements.txt stage-docker-import.sh $(RUN_WITH_BIN) $(DOCKERFILES) $(ENTRYPOINTS) twoway.py common.py zone_auth.py $(PY_SRC)
	"$(CURDIR)/stage-docker-import.sh"
	docker buildx build -q --platform $(PLATFORM) -f Dockerfile.twoway -t $(IMAGE_TWOWAY):$(TAG) --load .
	@docker image inspect $(IMAGE_TWOWAY):$(TAG) -f '{{.Id}}' | cut -d: -f2 > .image.twoway

push: build
	@[ -n "$${CR_PAT}" ] || { echo "CR_PAT not set. export CR_PAT=ghp_..."; exit 1; }
	echo "$$CR_PAT" | docker login ghcr.io -u jovlinger --password-stdin
	docker push $(IMAGE_APP):$(TAG)
	docker push $(IMAGE_TWOWAY):$(TAG)

clean:
	@docker image rm $(IMAGE_APP):$(TAG) 2>/dev/null || true
	@docker image rm $(IMAGE_TWOWAY):$(TAG) 2>/dev/null || true
	@rm -f .image.app .image.twoway
	@rm -rf .docker-import

test: build
	./test/run.sh

ci:
	@BRANCH=$$(git rev-parse --abbrev-ref HEAD); \
	test "$$BRANCH" = main || test "$$BRANCH" = master || { echo "Run from main or master"; exit 1; }; \
	echo "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" > .ci-trigger && \
	git add .ci-trigger && \
	git commit -m "ci: trigger thermo-onboard build" && \
	git push origin $$BRANCH
	@echo "Workflow triggered. See https://github.com/jovlinger/utils/actions"
