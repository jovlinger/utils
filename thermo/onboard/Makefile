# Build and push thermo-onboard-app and thermo-onboard-twoway to GHCR.
# Pi Zero 2 W: arm64 or armhf. Requires CR_PAT for push.
#
# Deploy (on the Pi or any host with this repo): from thermo/onboard run
#   make deploy
# That runs install/deploy.sh with REPO_PATH set to the utils checkout (git pull + deploy-compose).
.PHONY: all build images push push_images clean test test-local test-docker ci deploy

IMAGE_APP := ghcr.io/jovlinger/thermo-onboard-app
IMAGE_TWOWAY := ghcr.io/jovlinger/thermo-onboard-twoway
TAG ?= latest
# After `make push`, view on GitHub (package slug = image name after ghcr.io/jovlinger/):
#   https://github.com/jovlinger/utils/pkgs/container/thermo-onboard-app
#   https://github.com/jovlinger/utils/pkgs/container/thermo-onboard-twoway
# List: repo https://github.com/jovlinger/utils → Packages (sidebar), or https://github.com/jovlinger?tab=packages
# Pi Zero 2 W with 32-bit OS (armhf); use linux/arm64 for 64-bit OS
PLATFORM ?= linux/arm/v7
# Verbose docker build (plain streams RUN output; use `make ... DOCKER_BUILD_PROGRESS=auto` for TTY bars)
DOCKER_BUILD_PROGRESS ?= plain

RUN_WITH_BIN := $(abspath $(CURDIR)/../../bin/run-with-stdout-logged.py)

DOCKERFILES := Dockerfile.onboard Dockerfile.twoway
ENTRYPOINTS := docker-entrypoint-onboard.sh docker-entrypoint-twoway.sh
PY_SRC := $(wildcard *.py) $(wildcard heatpumpirctl/*.py)

all: build

# Alias for CI / thermo/test (Makefile calls `make images`).
images: build

build: .image.app .image.twoway

.image.app: Dockerfile.onboard requirements.txt stage-docker-import.sh $(RUN_WITH_BIN) $(DOCKERFILES) $(ENTRYPOINTS) $(PY_SRC) $(wildcard ../ui/*)
	"$(CURDIR)/stage-docker-import.sh"
	@echo "[build] $(IMAGE_APP):$(TAG) platform=$(PLATFORM) (this may take several minutes)..."
	docker buildx build --progress=$(DOCKER_BUILD_PROGRESS) --platform $(PLATFORM) -f Dockerfile.onboard -t $(IMAGE_APP):$(TAG) --load .
	@docker image inspect $(IMAGE_APP):$(TAG) -f '{{.Id}}' | cut -d: -f2 > .image.app

.image.twoway: Dockerfile.twoway requirements.txt stage-docker-import.sh $(RUN_WITH_BIN) $(DOCKERFILES) $(ENTRYPOINTS) twoway.py common.py zone_auth.py connectivity_watchdog.py docker-entrypoint-watchdog.sh $(PY_SRC)
	"$(CURDIR)/stage-docker-import.sh"
	@echo "[build] $(IMAGE_TWOWAY):$(TAG) platform=$(PLATFORM)..."
	docker buildx build --progress=$(DOCKER_BUILD_PROGRESS) --platform $(PLATFORM) -f Dockerfile.twoway -t $(IMAGE_TWOWAY):$(TAG) --load .
	@docker image inspect $(IMAGE_TWOWAY):$(TAG) -f '{{.Id}}' | cut -d: -f2 > .image.twoway

push: build
	# OR use dockerlogin function
	#@[ -n "$${CR_PAT}" ] || { echo "CR_PAT not set. export CR_PAT=ghp_..."; exit 1; }
	#echo "$$CR_PAT" | docker login ghcr.io -u jovlinger --password-stdin
	docker push $(IMAGE_APP):$(TAG)
	docker push $(IMAGE_TWOWAY):$(TAG)

clean:
	@docker image rm $(IMAGE_APP):$(TAG) 2>/dev/null || true
	@docker image rm $(IMAGE_TWOWAY):$(TAG) 2>/dev/null || true
	@rm -f .image.app .image.twoway
	@rm -rf .docker-import

# Host venv: pytest, UI harness, daikin scripts (./test/run.sh). Does not require Docker images.
test-local:
	./test/run.sh

# Compose / image integration lives under ../test (dockertest). Avoid duplicate image builds here.
test-docker:
	@echo "onboard: no standalone test-docker recipe (stack: cd ../test && make test-docker)"
	@true

test: test-local test-docker

ci:
	@BRANCH=$$(git rev-parse --abbrev-ref HEAD); \
	test "$$BRANCH" = main || test "$$BRANCH" = master || { echo "Run from main or master"; exit 1; }; \
	echo "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" > .ci-trigger && \
	git add .ci-trigger && \
	git commit -m "ci: trigger thermo-onboard build" && \
	git push origin $$BRANCH
	@echo "Workflow triggered. See https://github.com/jovlinger/utils/actions"

# On-target deploy: git pull at REPO root, then thermo/onboard/install/deploy-compose.sh (docker compose pull + up).
# Requires THERMO_ENV_FILE (e.g. export THERMO_ENV_FILE=config/kitchen.env) — see thermo/config/README.md.
# Default REPO root is two levels up from this dir (onboard -> thermo -> utils).
# Override checkout: make deploy DEPLOY_REPO=/path/to/utils
DEPLOY_REPO ?= $(abspath $(CURDIR)/../..)
deploy:
	@test -f "$(CURDIR)/install/deploy.sh" || { echo "deploy: missing install/deploy.sh"; exit 1; }
	@test -e "$(DEPLOY_REPO)/.git" || { echo "deploy: DEPLOY_REPO must be a git working tree: $(DEPLOY_REPO)"; exit 1; }
	@echo "[deploy] REPO_PATH=$(DEPLOY_REPO)"
	REPO_PATH="$(DEPLOY_REPO)" /bin/sh "$(CURDIR)/install/deploy.sh"
