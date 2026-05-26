# Common onboard entry points. Hardware-specific build/deploy details live under hardware/<backend>/.
.PHONY: all build images push push_images pull clean test test-local test-docker ci deploy

ONBOARD_BUILD_BACKEND ?= pizero2w
HARDWARE_DIR := hardware/$(ONBOARD_BUILD_BACKEND)

all: build

build images push push_images pull clean:
	@test -f "$(CURDIR)/$(HARDWARE_DIR)/Makefile" || { echo "missing hardware backend Makefile: $(HARDWARE_DIR)"; exit 1; }
	$(MAKE) -C "$(CURDIR)/$(HARDWARE_DIR)" ONBOARD_ROOT="$(CURDIR)" $@

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

# Room deploy: source THERMO_ENV_FILE, then dispatch to the configured hardware backend.
# Requires THERMO_ENV_FILE (e.g. export THERMO_ENV_FILE=config/kitchen.env) - see thermo/config/README.md.
# Default REPO root is two levels up from this dir (onboard -> thermo -> utils).
# Override checkout: make deploy DEPLOY_REPO=/path/to/utils
DEPLOY_REPO ?= $(abspath $(CURDIR)/../..)
deploy:
	@test -f "$(CURDIR)/install/deploy.sh" || { echo "deploy: missing install/deploy.sh"; exit 1; }
	@test -e "$(DEPLOY_REPO)/.git" || { echo "deploy: DEPLOY_REPO must be a git working tree: $(DEPLOY_REPO)"; exit 1; }
	@echo "[deploy] REPO_PATH=$(DEPLOY_REPO)"
	REPO_PATH="$(DEPLOY_REPO)" /bin/sh "$(CURDIR)/install/deploy.sh"
