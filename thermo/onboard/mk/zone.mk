# Shared targets for thermo/onboard/zones/<zone>/Makefile
# Include after setting ZONE_MAKEFILE, EXPECTED_ONBOARD_DEPLOY_BACKEND, and optionally
# THERMO_DEPLOY_EXECUTE (default 0; use 1 to flash Pico2W firmware).

ifndef ZONE_MAKEFILE
$(error set ZONE_MAKEFILE := $$(abspath $$(lastword $$(MAKEFILE_LIST))) in zones/<zone>/Makefile before including this file)
endif

ONBOARD_ROOT := $(abspath $(dir $(ZONE_MAKEFILE))/../..)
THERMO_ROOT := $(abspath $(ONBOARD_ROOT)/..)
REPO_ROOT := $(abspath $(THERMO_ROOT)/..)
ZONE_DIR := $(abspath $(dir $(ZONE_MAKEFILE)))
ZONE_NAME := $(notdir $(ZONE_DIR))
THERMO_ENV_FILE := zones/$(ZONE_NAME)/zone.env
THERMO_DEPLOY_EXECUTE ?= 0

.PHONY: all build clean test deploy print-config

all: build

print-config:
	@echo "ZONE_NAME=$(ZONE_NAME)"
	@echo "ZONE_DIR=$(ZONE_DIR)"
	@echo "THERMO_ENV_FILE=$(THERMO_ENV_FILE)"
	@echo "EXPECTED_ONBOARD_DEPLOY_BACKEND=$(EXPECTED_ONBOARD_DEPLOY_BACKEND)"
	@echo "THERMO_DEPLOY_EXECUTE=$(THERMO_DEPLOY_EXECUTE)"

build:
	$(MAKE) -C $(ONBOARD_ROOT) build

clean:
	$(MAKE) -C $(ONBOARD_ROOT) clean

test: build
	$(MAKE) -C $(ONBOARD_ROOT) test

deploy: test
	$(MAKE) -C $(ONBOARD_ROOT) deploy-zone \
		THERMO_ENV_FILE=$(THERMO_ENV_FILE) \
		EXPECTED_ONBOARD_DEPLOY_BACKEND=$(EXPECTED_ONBOARD_DEPLOY_BACKEND) \
		THERMO_DEPLOY_EXECUTE=$(THERMO_DEPLOY_EXECUTE)
