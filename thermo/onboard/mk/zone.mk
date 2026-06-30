# Shared targets for thermo/onboard/zones/<zone>/Makefile
# Include after setting ZONE_MAKEFILE and EXPECTED_ONBOARD_DEPLOY_BACKEND.

ifndef ZONE_MAKEFILE
$(error set ZONE_MAKEFILE := $$(abspath $$(lastword $$(MAKEFILE_LIST))) in zones/<zone>/Makefile before including this file)
endif

ONBOARD_ROOT := $(abspath $(dir $(ZONE_MAKEFILE))/../..)
THERMO_ROOT := $(abspath $(ONBOARD_ROOT)/..)
REPO_ROOT := $(abspath $(THERMO_ROOT)/..)
ZONE_DIR := $(abspath $(dir $(ZONE_MAKEFILE)))
ZONE_NAME := $(notdir $(ZONE_DIR))
THERMO_ENV_FILE := onboard/zones/$(ZONE_NAME)/zone.env
DEPLOY_REPO ?=

.PHONY: all build clean test deploy predeploy print-config

all: build

print-config:
	@echo "ZONE_NAME=$(ZONE_NAME)"
	@echo "ZONE_DIR=$(ZONE_DIR)"
	@echo "THERMO_ENV_FILE=$(THERMO_ENV_FILE)"
	@echo "EXPECTED_ONBOARD_DEPLOY_BACKEND=$(EXPECTED_ONBOARD_DEPLOY_BACKEND)"

build:
	$(MAKE) -C $(ONBOARD_ROOT) build ONBOARD_BUILD_BACKEND=$(EXPECTED_ONBOARD_DEPLOY_BACKEND)

clean:
	$(MAKE) -C $(ONBOARD_ROOT) clean ONBOARD_BUILD_BACKEND=$(EXPECTED_ONBOARD_DEPLOY_BACKEND)

test: build
	$(MAKE) -C $(ONBOARD_ROOT) test

predeploy:
	$(MAKE) -C $(ONBOARD_ROOT) deploy-preflight \
		THERMO_ENV_FILE=$(THERMO_ENV_FILE) \
		EXPECTED_ONBOARD_DEPLOY_BACKEND=$(EXPECTED_ONBOARD_DEPLOY_BACKEND) \
		DEPLOY_REPO=$(DEPLOY_REPO)

deploy: predeploy test
	$(MAKE) -C $(ONBOARD_ROOT) deploy-zone \
		THERMO_ENV_FILE=$(THERMO_ENV_FILE) \
		EXPECTED_ONBOARD_DEPLOY_BACKEND=$(EXPECTED_ONBOARD_DEPLOY_BACKEND) \
		DEPLOY_REPO=$(DEPLOY_REPO)
