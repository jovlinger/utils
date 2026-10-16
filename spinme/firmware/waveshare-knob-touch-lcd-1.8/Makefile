# Knob UI. pio is the spinme venv binary, not a system PlatformIO.
SPINME := $(abspath $(dir $(lastword $(MAKEFILE_LIST)))/../..)
PIO := $(SPINME)/.venv-tools/bin/pio
ENV := waveshare_knob_18_s3

.PHONY: build install screenshot

build:
	test -x "$(PIO)"
	PATH="$(SPINME)/.venv-tools/bin:$$PATH" "$(PIO)" run -e $(ENV)

# Build if needed, then flash the UI image. Do not use the encoder_debug env.
install:
	test -x "$(PIO)"
	PATH="$(SPINME)/.venv-tools/bin:$$PATH" "$(PIO)" run -e $(ENV) -t upload

# Host PNG of the status UI. Volumio lines are placeholders, not a live getState.
screenshot:
	cd "$(SPINME)" && .venv/bin/python -m screenmock
