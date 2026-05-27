# Build/check/deploy Pico2W Rust firmware.
.PHONY: all build check host-check firmware-check firmware-build images push push_images pull clean deploy print-config

ONBOARD_ROOT ?= $(abspath $(CURDIR)/../..)
CARGO ?= $(if $(wildcard $(HOME)/.cargo/bin/cargo),$(HOME)/.cargo/bin/cargo,cargo)
PICO2W_TARGET ?= thumbv8m.main-none-eabihf
PICO2W_LEGACY_TARGET ?= thumbv6m-none-eabi
CARGO_MANIFEST := $(CURDIR)/Cargo.toml

all: build

build: host-check firmware-check

check: build

host-check:
	$(CARGO) test --manifest-path "$(CARGO_MANIFEST)" --lib

firmware-check:
	$(CARGO) check --manifest-path "$(CARGO_MANIFEST)" --lib --no-default-features --target "$(PICO2W_TARGET)"
	$(CARGO) check --manifest-path "$(CARGO_MANIFEST)" --bin ledw_status --no-default-features --features firmware --target "$(PICO2W_TARGET)"

firmware-build:
	$(CARGO) build --manifest-path "$(CARGO_MANIFEST)" --bin ledw_status --release --no-default-features --features firmware --target "$(PICO2W_TARGET)"

images: build

push push_images pull:
	@echo "[pico2w] no container image step for Pico2W firmware"

print-config:
	@echo "ONBOARD_ROOT=$(ONBOARD_ROOT)"
	@echo "CARGO=$(CARGO)"
	@echo "PICO2W_TARGET=$(PICO2W_TARGET)"
	@echo "PICO2W_LEGACY_TARGET=$(PICO2W_LEGACY_TARGET)"

deploy:
	/bin/sh "$(CURDIR)/install/deploy.sh"

clean:
	$(CARGO) clean --manifest-path "$(CARGO_MANIFEST)"
