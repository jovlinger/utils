# MicroPython path for ESP32-S3 office onboard.
.PHONY: all build test all-tests testall check host-check images push push_images pull clean print-config

ONBOARD_ROOT ?= $(abspath $(CURDIR)/../..)
REPO_ROOT ?= $(abspath $(CURDIR)/../../../..)
PYTEST ?= $(ONBOARD_ROOT)/.venv/bin/pytest
THERMO_DEPLOY_GIT_SHA ?= $(shell git -C "$(REPO_ROOT)" rev-parse HEAD 2>/dev/null)
THERMO_DEPLOY_GIT_SHA_SHORT ?= $(shell git -C "$(REPO_ROOT)" rev-parse --short HEAD 2>/dev/null)
THERMO_DEPLOY_BACKEND ?= esp32s3
export THERMO_DEPLOY_GIT_SHA THERMO_DEPLOY_GIT_SHA_SHORT THERMO_DEPLOY_BACKEND

all: build

build: host-check

test: host-check

all-tests: test

testall: all-tests

check: build

host-check:
	@test -x "$(PYTEST)" || (echo "missing $(PYTEST); run ./create_pipenv.sh thermo/onboard" >&2; exit 1)
	cd "$(CURDIR)" && "$(PYTEST)" -q test/

images push push_images pull:
	@echo "[esp32s3] no container image step for ESP32-S3 MicroPython firmware"

print-config:
	@echo "ONBOARD_ROOT=$(ONBOARD_ROOT)"
	@echo "PYTEST=$(PYTEST)"

clean:
	rm -rf "$(CURDIR)/test/__pycache__" "$(CURDIR)/mp/__pycache__" "$(CURDIR)/.pytest_cache"
