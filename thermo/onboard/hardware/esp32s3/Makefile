# Build/check ESP32-S3 Rust firmware scaffold.
.PHONY: all build test testall check host-check images push push_images pull clean print-config

ONBOARD_ROOT ?= $(abspath $(CURDIR)/../..)
REPO_ROOT ?= $(abspath $(CURDIR)/../../../..)
CARGO ?= $(if $(wildcard $(HOME)/.cargo/bin/cargo),$(HOME)/.cargo/bin/cargo,cargo)
THERMO_DEPLOY_GIT_SHA ?= $(shell git -C "$(REPO_ROOT)" rev-parse HEAD 2>/dev/null)
THERMO_DEPLOY_GIT_SHA_SHORT ?= $(shell git -C "$(REPO_ROOT)" rev-parse --short HEAD 2>/dev/null)
THERMO_DEPLOY_BACKEND ?= esp32s3
export THERMO_DEPLOY_GIT_SHA THERMO_DEPLOY_GIT_SHA_SHORT THERMO_DEPLOY_BACKEND
CARGO_MANIFEST := $(CURDIR)/Cargo.toml

all: build

build: host-check

test: host-check

testall: test

check: build

host-check:
	$(CARGO) test --manifest-path "$(CARGO_MANIFEST)" --lib

images push push_images pull:
	@echo "[esp32s3] no container image step for ESP32-S3 firmware"

print-config:
	@echo "ONBOARD_ROOT=$(ONBOARD_ROOT)"
	@echo "CARGO=$(CARGO)"

clean:
	$(CARGO) clean --manifest-path "$(CARGO_MANIFEST)"
