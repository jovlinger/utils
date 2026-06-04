# Build and push Pi Zero 2 W thermo-onboard images to GHCR.
# Default target platform is 32-bit Raspberry Pi OS on Pi Zero 2 W.
.PHONY: all build test images push push_images pull clean

ONBOARD_ROOT ?= $(abspath $(CURDIR)/../..)

IMAGE_APP := ghcr.io/jovlinger/thermo-onboard-app
IMAGE_TWOWAY := ghcr.io/jovlinger/thermo-onboard-twoway
TAG ?= latest

# !!! DO NOT CHANGE THE DEFAULT PLATFORM !!!
# Pi Zero 2 W (BCM2710A1) currently runs 32-bit Raspberry Pi OS (armhf / ARMv7).
# The default below is what GHCR ships and what deploy pulls onto the Pi.
# To experiment with a 64-bit OS, override on the command line:
#   make build PLATFORM=linux/arm64
PLATFORM ?= linux/arm/v7
DOCKER_BUILD_PROGRESS ?= plain
PUSH_RETRIES ?= 3

RUN_WITH_BIN := $(abspath $(ONBOARD_ROOT)/../../extdeps/run-with-stdout-logged.py)
DOCKERFILES := Dockerfile.onboard Dockerfile.twoway
ENTRYPOINTS := docker-entrypoint-onboard.sh docker-entrypoint-twoway.sh docker-entrypoint-watchdog.sh
PY_SRC := $(wildcard $(ONBOARD_ROOT)/common/*.py) $(wildcard $(ONBOARD_ROOT)/common/heatpumpirctl/*.py) $(wildcard $(CURDIR)/*.py)
UI_SRC := $(wildcard $(ONBOARD_ROOT)/../ui/*)

APP_MARKER := $(ONBOARD_ROOT)/.image.app
TWOWAY_MARKER := $(ONBOARD_ROOT)/.image.twoway

all: build

images: build

build: $(APP_MARKER) $(TWOWAY_MARKER)

test:
	@echo "[pizero2w] image build only; Python tests: make -C $(ONBOARD_ROOT) test"

$(APP_MARKER): Dockerfile.onboard $(ONBOARD_ROOT)/requirements.txt stage-docker-import.sh $(RUN_WITH_BIN) $(DOCKERFILES) $(ENTRYPOINTS) $(PY_SRC) $(UI_SRC)
	"$(CURDIR)/stage-docker-import.sh"
	@echo "[build] $(IMAGE_APP):$(TAG) platform=$(PLATFORM) (this may take several minutes)..."
	docker buildx build --progress=$(DOCKER_BUILD_PROGRESS) --platform $(PLATFORM) -f "$(CURDIR)/Dockerfile.onboard" -t $(IMAGE_APP):$(TAG) --load "$(ONBOARD_ROOT)"
	@docker image inspect $(IMAGE_APP):$(TAG) -f '{{.Id}}' | cut -d: -f2 > "$@"

$(TWOWAY_MARKER): Dockerfile.twoway $(ONBOARD_ROOT)/requirements.txt stage-docker-import.sh $(RUN_WITH_BIN) $(DOCKERFILES) $(ENTRYPOINTS) $(ONBOARD_ROOT)/common/twoway.py $(ONBOARD_ROOT)/common/logging_config.py $(ONBOARD_ROOT)/common/zone_auth.py connectivity_watchdog.py $(PY_SRC)
	"$(CURDIR)/stage-docker-import.sh"
	@echo "[build] $(IMAGE_TWOWAY):$(TAG) platform=$(PLATFORM)..."
	docker buildx build --progress=$(DOCKER_BUILD_PROGRESS) --platform $(PLATFORM) -f "$(CURDIR)/Dockerfile.twoway" -t $(IMAGE_TWOWAY):$(TAG) --load "$(ONBOARD_ROOT)"
	@docker image inspect $(IMAGE_TWOWAY):$(TAG) -f '{{.Id}}' | cut -d: -f2 > "$@"

push: build
	@push_with_retry() { \
		img=$$1; \
		for n in $$(seq 1 $(PUSH_RETRIES)); do \
			echo "[push] attempt $$n/$(PUSH_RETRIES): docker push $$img"; \
			docker push "$$img" && { echo "[push] ok: $$img"; return 0; }; \
			[ "$$n" -lt "$(PUSH_RETRIES)" ] && sleep 2; \
		done; \
		echo "[push] giving up on $$img after $(PUSH_RETRIES) attempts" >&2; \
		return 1; \
	}; \
	for img in $(IMAGE_APP):$(TAG) $(IMAGE_TWOWAY):$(TAG); do \
		push_with_retry "$$img" || exit 1; \
	done

push_images: push

pull:
	@pull_no_retry() { \
		img=$$1; \
		docker pull "$$img" && { echo "[pull] ok: $$img"; return 0; }; \
		echo "[pull] giving up on $$img after 1 attempts" >&2; \
		return 1; \
	}; \
	for img in $(IMAGE_APP):$(TAG) $(IMAGE_TWOWAY):$(TAG); do \
		pull_no_retry "$$img" || exit 1; \
	done

clean:
	@docker image rm $(IMAGE_APP):$(TAG) 2>/dev/null || true
	@docker image rm $(IMAGE_TWOWAY):$(TAG) 2>/dev/null || true
	@rm -f "$(APP_MARKER)" "$(TWOWAY_MARKER)"
	@rm -rf "$(ONBOARD_ROOT)/.docker-import"
