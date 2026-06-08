# Build/check/deploy Pico2W Rust firmware.
.PHONY: all build test check host-check firmware-check firmware-build images push push_images pull clean deploy print-config

ONBOARD_ROOT ?= $(abspath $(CURDIR)/../..)
REPO_ROOT ?= $(abspath $(CURDIR)/../../../..)
CARGO ?= $(if $(wildcard $(HOME)/.cargo/bin/cargo),$(HOME)/.cargo/bin/cargo,cargo)
THERMO_DEPLOY_GIT_SHA ?= $(shell git -C "$(REPO_ROOT)" rev-parse HEAD 2>/dev/null)
THERMO_DEPLOY_GIT_SHA_SHORT ?= $(shell git -C "$(REPO_ROOT)" rev-parse --short HEAD 2>/dev/null)
THERMO_DEPLOY_BACKEND ?= pico2w
export THERMO_DEPLOY_GIT_SHA THERMO_DEPLOY_GIT_SHA_SHORT THERMO_DEPLOY_BACKEND
PICO2W_TARGET ?= thumbv8m.main-none-eabihf
PICO2W_LEGACY_TARGET ?= thumbv6m-none-eabi
CARGO_MANIFEST := $(CURDIR)/Cargo.toml

all: build

build: host-check firmware-check

test: host-check

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

.PHONY: hat-stl hat-vox-stl hat-trace-stl
hat-stl:
	hat/generate_sensor_hat_stl.py
	@echo "CARGO=$(CARGO)"
	@echo "PICO2W_TARGET=$(PICO2W_TARGET)"
	@echo "PICO2W_LEGACY_TARGET=$(PICO2W_LEGACY_TARGET)"

hat-vox-stl:
	hat/check_vox.py "hat/up-side.vox"
	"$(REPO_ROOT)/vox2stl/vox2stl.py" "hat/up-side.vox" --mode full --layer trace --base-layer base --output "hat/thermo-pico2w-sensor-hat-v1-up-side-vox.stl" --solid-name thermo_pico2w_sensor_hat_v1_up_side_vox

hat-trace-stl:
	hat/check_vox.py "hat/up-side.vox"
	"$(REPO_ROOT)/vox2stl/vox2stl.py" "hat/up-side.vox" --layer trace --output "hat/thermo-pico2w-sensor-hat-v1-up-side-trace.stl" --solid-name thermo_pico2w_sensor_hat_v1_up_side_trace

deploy:
	/bin/sh "$(CURDIR)/install/deploy.sh"

clean:
	$(CARGO) clean --manifest-path "$(CARGO_MANIFEST)"
