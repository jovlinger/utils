# mpd_indexer -- dont-walk contract tests + SHD armhf MPD build/deploy.
#
# Fast tests (picked up by root `make test`):
#   make test
#
# Build dont-walk MPD for miniDSP SHD Neo3 (armhf, glibc 2.28 / Debian 10):
#   make build-dontwalk-armhf MPD_SRC=/path/to/jovlinger/MPD
#   make build-dontwalk-armhf MPD_SRC=... BUILD_HOST=gmk.local
#
# Deploy that binary to the SHD (keeps /usr/bin/mpd.stock-0.23.15):
#   make deploy-dontwalk-shd SHD_PASS=...
#   make deploy-dontwalk-shd SHD_PASS=... SHD_HOST=192.168.88.39
#
# Rollback on SHD:
#   make rollback-dontwalk-shd SHD_PASS=...
#
# Assumptions (see scripts/*.sh headers):
#   - MPD_SRC is jovlinger/MPD with dont-walk Walk.cxx (e.g. d6d78baa-dontwalk).
#   - SHD userland is armhf glibc 2.28; Buster sysroot is required.
#   - Stock systemd unit stays Type=notify; drop-in only adds /etc/mpd.conf.
#   - Node scanFolder rememberReal is separate (volumio_scanfolder_mpdignore/).

MPD_SRC ?=
BUILD_HOST ?=
OUT_DIR := $(abspath out)
MPD_BIN := $(OUT_DIR)/mpd
SHD_HOST ?= 192.168.88.39
SHD_USER ?= volumiooem
SHD_PASS ?=

.PHONY: binlinks test all-tests \
	build-dontwalk-armhf deploy-dontwalk-shd rollback-dontwalk-shd \
	prove-dontwalk-tags start-test-container verify-dontwalk-shd \
	test-enqueue-prefixes-docker

binlinks:
	@:

test:
	python3 -m unittest discover -s . -p 'test_*.py' -v

all-tests: test

build-dontwalk-armhf:
	@if [ -z "$(MPD_SRC)" ]; then \
	  echo "Set MPD_SRC to a dont-walk MPD checkout (meson.build + Walk.cxx)."; \
	  exit 1; \
	fi
	chmod +x scripts/build-dontwalk-buster-armhf.sh scripts/build-dontwalk-inside-buster.sh
	MPD_SRC="$(MPD_SRC)" OUT_DIR="$(OUT_DIR)" BUILD_HOST="$(BUILD_HOST)" \
	  ./scripts/build-dontwalk-buster-armhf.sh

deploy-dontwalk-shd:
	@if [ -z "$(SHD_PASS)" ]; then \
	  echo "Set SHD_PASS (volumiooem SSH/sudo password)."; \
	  exit 1; \
	fi
	chmod +x scripts/deploy-dontwalk-shd.sh scripts/verify-dontwalk-shd.sh
	MPD_BIN="$(MPD_BIN)" SHD_HOST="$(SHD_HOST)" SHD_USER="$(SHD_USER)" \
	  SHD_PASS="$(SHD_PASS)" ./scripts/deploy-dontwalk-shd.sh

verify-dontwalk-shd:
	@if [ -z "$(SHD_PASS)" ]; then \
	  echo "Set SHD_PASS (volumiooem SSH/sudo password)."; \
	  exit 1; \
	fi
	chmod +x scripts/verify-dontwalk-shd.sh
	SHD_HOST="$(SHD_HOST)" SHD_USER="$(SHD_USER)" SHD_PASS="$(SHD_PASS)" \
	  ./scripts/verify-dontwalk-shd.sh

rollback-dontwalk-shd:
	@if [ -z "$(SHD_PASS)" ]; then \
	  echo "Set SHD_PASS (volumiooem SSH/sudo password)."; \
	  exit 1; \
	fi
	chmod +x scripts/rollback-dontwalk-shd.sh
	SHD_HOST="$(SHD_HOST)" SHD_USER="$(SHD_USER)" SHD_PASS="$(SHD_PASS)" \
	  ./scripts/rollback-dontwalk-shd.sh

# Proof: SHD-shaped NAS/gmk/files + _tags indexed, _meta ignored.
# Prefers local Docker; falls back to native macOS/Linux build when Docker is down.
prove-dontwalk-tags:
	chmod +x scripts/prove-dontwalk-tags-container.sh \
	  scripts/prove-dontwalk-tags-inside.sh \
	  scripts/prove-dontwalk-tags-native.sh
	@if docker info >/dev/null 2>&1; then \
	  MPD_SRC="$(MPD_SRC)" ./scripts/prove-dontwalk-tags-container.sh; \
	else \
	  echo "Docker down; native prove on this host."; \
	  MPD_SRC="$(MPD_SRC)" ./scripts/prove-dontwalk-tags-native.sh; \
	fi

# Docker e2e for tag-prefix enqueue. Not part of `make test` or `all-tests`.
#   make test-enqueue-prefixes-docker MPD_SRC=$HOME/github.com/jovlinger/MPD
test-enqueue-prefixes-docker:
	@if [ -z "$(MPD_SRC)" ]; then \
	  echo "Set MPD_SRC to a dont-walk MPD checkout (meson.build + Walk.cxx)."; \
	  exit 1; \
	fi
	chmod +x scripts/enqueue-prefixes-container.sh scripts/enqueue-prefixes-inside.sh
	MPD_SRC="$(MPD_SRC)" ./scripts/enqueue-prefixes-container.sh

# Start test container with newest MPD_SRC: recreate nested-_tags bug, then prove fix.
#   make start-test-container MPD_SRC=$HOME/github.com/jovlinger/MPD
#   make start-test-container MPD_SRC=... INTERACTIVE=1
start-test-container:
	@if [ -z "$(MPD_SRC)" ]; then \
	  echo "Set MPD_SRC to the newest dont-walk MPD checkout."; \
	  exit 1; \
	fi
	chmod +x scripts/start-test-container.sh scripts/test-container-entry.sh
	MPD_SRC="$(MPD_SRC)" INTERACTIVE="$(INTERACTIVE)" \
	  ./scripts/start-test-container.sh
