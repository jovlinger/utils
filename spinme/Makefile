# spinme top-level Make: host tests + board install (nucleus USB vs tasks OTA).
#
# Install (from this directory):
#   make usbinstallall      # rebuild + full USB flash (nucleus + linked actors)
#   make usbinstalltasks    # rebuild task blobs; USB-only tasks path (see note)
#   make otainstalltasks    # rebuild task blobs; PUT /kv/<key> to SPINME_HOST
#
# Env: SPINME_PIO, UPLOAD_PORT, SPINME_HOST (default spinme.local),
#      SPINME_OTA_REQUIRE_BLOBS=1 to fail otainstalltasks when stage is empty.

BINLINKS := ../binlinks
ROOT := $(abspath $(dir $(lastword $(MAKEFILE_LIST))))
SCRIPTS := $(ROOT)/scripts
FW_DIR := $(ROOT)/firmware/waveshare-knob-touch-lcd-1.8
PIO_ENV := waveshare_knob_18_s3
TASKS_DIR := $(ROOT)/build/tasks
BUILD_DIR := $(ROOT)/build

.PHONY: binlinks test all-tests test-taskevent
.PHONY: build build-nucleus build-tasks
.PHONY: clean distclean
.PHONY: usbinstallall usbinstalltasks otainstalltasks

binlinks:
	mkdir -p $(BINLINKS)
	ln -sf ../spinme/host/scripts/spinmecli $(BINLINKS)/spinmecli

# Fast suite: Python TaskEvent SoT + host C tests when present.
test: test-taskevent
	$(MAKE) -C host test

test-taskevent:
	cd "$(ROOT)" && PYTHONPATH=. detest --runner=unittest taskevent/test_taskevent.py
	cd "$(ROOT)" && PYTHONPATH=. ./taskevent/gen_c_header.py --check

all-tests: test

# --- nucleus / tasks build -----------------------------------------------

build: build-nucleus build-tasks

build-nucleus:
	PIO="$$($(SCRIPTS)/resolve_pio.sh)"; \
	cd "$(FW_DIR)" && "$$PIO" run -e "$(PIO_ENV)"

build-tasks: $(TASKS_DIR)/.built

$(TASKS_DIR)/.built: $(SCRIPTS)/build_tasks.sh
	$(SCRIPTS)/build_tasks.sh "$(TASKS_DIR)"

# --- install -------------------------------------------------------------

usbinstallall: build
	PIO="$$($(SCRIPTS)/resolve_pio.sh)"; \
	PORT="$$($(SCRIPTS)/resolve_upload_port.sh)"; \
	cd "$(FW_DIR)" && "$$PIO" run -e "$(PIO_ENV)" -t upload --upload-port "$$PORT"

# Tasks-only over USB: no separate tasks partition yet (all-but-nucleus still
# linked into the USB image). Staging still runs; delivery is OTA PUT when
# blobs exist. Set SPINME_USB_TASKS_FORCE_FULL=1 to fall back to full USB flash.
usbinstalltasks: build-tasks
	@if [ "$(SPINME_USB_TASKS_FORCE_FULL)" = "1" ]; then \
	  $(MAKE) usbinstallall; \
	else \
	  echo "usbinstalltasks: no tasks-only USB partition yet; delivering via OTA path"; \
	  $(MAKE) otainstalltasks; \
	fi

otainstalltasks: build-tasks
	$(SCRIPTS)/ota_install_tasks.sh "$(or $(SPINME_HOST),spinme.local)" "$(TASKS_DIR)"

# --- clean ---------------------------------------------------------------

# clean: host C test objects + staged tasks + PlatformIO build for the active env.
clean:
	$(MAKE) -C host clean || true
	rm -rf "$(TASKS_DIR)"
	PIO="$$($(SCRIPTS)/resolve_pio.sh)"; \
	cd "$(FW_DIR)" && "$$PIO" run -e "$(PIO_ENV)" -t clean

# distclean: clean + wipe broader build caches under spinme/build and PIO.
distclean: clean
	rm -rf "$(BUILD_DIR)"
	rm -rf "$(FW_DIR)/.pio"
