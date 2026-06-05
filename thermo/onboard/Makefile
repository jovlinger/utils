# Thermo onboard: shared build/test and per-zone deploy under zones/.
.PHONY: all build clean test deploy deploy-preflight deploy-zone ci

ONBOARD_ROOT := $(abspath $(CURDIR))
THERMO_ROOT := $(abspath $(ONBOARD_ROOT)/..)
REPO_ROOT := $(abspath $(THERMO_ROOT)/..)
HARDWARE_BACKENDS := pizero2w pico2w
ZONES := kitchen office bedroom

all: build

build:
	@for backend in $(HARDWARE_BACKENDS); do \
		echo "[onboard] build hardware/$$backend"; \
		$(MAKE) -C hardware/$$backend ONBOARD_ROOT="$(ONBOARD_ROOT)" build || exit $$?; \
	done

clean:
	@for backend in $(HARDWARE_BACKENDS); do \
		$(MAKE) -C hardware/$$backend ONBOARD_ROOT="$(ONBOARD_ROOT)" clean || exit $$?; \
	done

test:
	./test/run.sh

# Called from zones/<zone>/Makefile (see mk/zone.mk).
DEPLOY_REPO ?=
deploy-preflight:
	@test -n "$(THERMO_ENV_FILE)" || { echo "deploy-preflight: THERMO_ENV_FILE not set"; exit 1; }
	@test -f "$(THERMO_ROOT)/$(THERMO_ENV_FILE)" || { echo "deploy-preflight: missing $(THERMO_ROOT)/$(THERMO_ENV_FILE)"; exit 1; }
	REPO_PATH="$(if $(DEPLOY_REPO),$(DEPLOY_REPO),$(REPO_ROOT))" \
		EXPECTED_ONBOARD_DEPLOY_BACKEND="$(EXPECTED_ONBOARD_DEPLOY_BACKEND)" \
		THERMO_ENV_FILE="$(THERMO_ENV_FILE)" \
		/bin/sh "$(ONBOARD_ROOT)/install/deploy.sh" --preflight

deploy-zone:
	@test -n "$(THERMO_ENV_FILE)" || { echo "deploy-zone: THERMO_ENV_FILE not set"; exit 1; }
	@test -f "$(THERMO_ROOT)/$(THERMO_ENV_FILE)" || { echo "deploy-zone: missing $(THERMO_ROOT)/$(THERMO_ENV_FILE)"; exit 1; }
	REPO_PATH="$(if $(DEPLOY_REPO),$(DEPLOY_REPO),$(REPO_ROOT))" \
		EXPECTED_ONBOARD_DEPLOY_BACKEND="$(EXPECTED_ONBOARD_DEPLOY_BACKEND)" \
		THERMO_ENV_FILE="$(THERMO_ENV_FILE)" \
		/bin/sh "$(ONBOARD_ROOT)/install/deploy.sh"

# Convenience: make deploy ZONE=office
ZONE ?=
deploy:
	@if [ -z "$(ZONE)" ]; then \
		echo "Usage: make deploy ZONE=<kitchen|office|bedroom>"; \
		echo "   or: make -C zones/<zone> deploy"; \
		exit 1; \
	fi
	$(MAKE) -C zones/$(ZONE) deploy \
		DEPLOY_REPO="$(DEPLOY_REPO)"

ci:
	@BRANCH=$$(git -C "$(REPO_ROOT)" rev-parse --abbrev-ref HEAD); \
	test "$$BRANCH" = main || test "$$BRANCH" = master || { echo "Run from main or master"; exit 1; }; \
	echo "$$(date -u +%Y-%m-%dT%H:%M:%SZ)" > .ci-trigger && \
	git -C "$(REPO_ROOT)" add thermo/onboard/.ci-trigger && \
	git -C "$(REPO_ROOT)" commit -m "ci: trigger thermo-onboard build" && \
	git -C "$(REPO_ROOT)" push origin $$BRANCH
	@echo "Workflow triggered. See https://github.com/jovlinger/utils/actions"
