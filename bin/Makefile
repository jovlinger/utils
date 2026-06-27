# Manually refreshed snapshots from the sister `bin` repo (no submodules).
#
# Files in *this* ``utils/bin/`` are committed copies. Default source checkout:
# ``../../bin`` = sibling of ``utils/`` (``.../jovlinger/utils`` + ``.../jovlinger/bin``).
#
#   make -C bin all
#
# Override:
#
#   make -C bin BIN_REPO=/path/to/bin all
#
# Thermo references ``../../bin/run-with-stdout-logged.py`` from ``thermo/onboard``.
#
# Why not requirements.txt (yet): Docker builds COPY these files from the repo
# tree into image context; pip installs into site-packages, not a stable path for
# COPY. Later, if we publish a tiny installable package (PyPI or git+VCS with
# pyproject.toml) and teach Dockerfiles to `pip install` it, we could drop this
# mirror in favor of a versioned dependency.

BIN_REPO ?= $(abspath $(CURDIR)/../../bin)
SRC_RUN := $(BIN_REPO)/run-with-stdout-logged.py
SRC_MOCK := $(BIN_REPO)/mock_cmd.py
DST_RUN := $(CURDIR)/run-with-stdout-logged.py
DST_MOCK := $(CURDIR)/mock_cmd.py
VERSION := $(CURDIR)/VERSION

.PHONY: all binlinks
all:
	@test -f "$(SRC_RUN)" || (echo "bin: missing $(SRC_RUN)" >&2; echo "  Clone bin next to utils or: make BIN_REPO=/path/to/bin all" >&2; exit 1)
	@test -f "$(SRC_MOCK)" || (echo "bin: missing $(SRC_MOCK)" >&2; echo "  Clone bin next to utils or: make BIN_REPO=/path/to/bin all" >&2; exit 1)
	cp -p "$(SRC_RUN)" "$(DST_RUN)"
	cp -p "$(SRC_MOCK)" "$(DST_MOCK)"
	date -u +%Y-%m-%dT%H-%M-%SZ > "$(VERSION)"
	@echo "Updated $(DST_RUN) <- $(SRC_RUN)"
	@echo "Updated $(DST_MOCK) <- $(SRC_MOCK)"
	@echo "Recorded $(VERSION) $$(cat $(VERSION))"

binlinks:
	@:
