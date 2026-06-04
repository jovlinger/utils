# Manually refreshed snapshots from the sister `bin` repo (no submodules).
#
# Files in *this* ``utils/extdeps/`` are committed copies. Default source checkout:
# ``../../bin`` = sibling of ``utils/`` (``.../jovlinger/utils`` + ``.../jovlinger/bin``).
#
#   make -C extdeps all
#
# Override:
#
#   make -C extdeps BIN_REPO=/path/to/bin all
#
# Thermo references ``../../extdeps/run-with-stdout-logged.py`` from ``thermo/onboard``.
# Python CLIs use ``#!/usr/bin/env venv-run`` on ``.py`` files; put ``extdeps/`` on PATH
# (``venv-run`` symlink) like ``bin/`` repo root for bin tools.
#
# Why not requirements.txt (yet): Docker builds COPY these files from the repo
# tree into image context; pip installs into site-packages, not a stable path for
# COPY. Later, if we publish a tiny installable package (PyPI or git+VCS with
# pyproject.toml) and teach Dockerfiles to `pip install` it, we could drop this
# mirror in favor of a versioned dependency.

BIN_REPO ?= $(abspath $(CURDIR)/../../bin)
SRC_RUN := $(BIN_REPO)/run-with-stdout-logged.py
SRC_MOCK := $(BIN_REPO)/mock_cmd.py
SRC_VENV_RUN := $(BIN_REPO)/venv-run.py
SRC_VENV_RUN_LAUNCH := $(BIN_REPO)/venv-run-launch.py
DST_RUN := $(CURDIR)/run-with-stdout-logged.py
DST_MOCK := $(CURDIR)/mock_cmd.py
DST_VENV_RUN := $(CURDIR)/venv-run.py
DST_VENV_RUN_LAUNCH := $(CURDIR)/venv-run-launch.py
DST_VENV_RUN_LINK := $(CURDIR)/venv-run
VERSION := $(CURDIR)/VERSION

.PHONY: all
all:
	@test -f "$(SRC_RUN)" || (echo "extdeps: missing $(SRC_RUN)" >&2; echo "  Clone bin next to utils or: make -C extdeps BIN_REPO=/path/to/bin all" >&2; exit 1)
	@test -f "$(SRC_MOCK)" || (echo "extdeps: missing $(SRC_MOCK)" >&2; echo "  Clone bin next to utils or: make -C extdeps BIN_REPO=/path/to/bin all" >&2; exit 1)
	@test -f "$(SRC_VENV_RUN)" || (echo "extdeps: missing $(SRC_VENV_RUN)" >&2; echo "  Clone bin next to utils or: make -C extdeps BIN_REPO=/path/to/bin all" >&2; exit 1)
	@test -f "$(SRC_VENV_RUN_LAUNCH)" || (echo "extdeps: missing $(SRC_VENV_RUN_LAUNCH)" >&2; echo "  Clone bin next to utils or: make -C extdeps BIN_REPO=/path/to/bin all" >&2; exit 1)
	cp -p "$(SRC_RUN)" "$(DST_RUN)"
	cp -p "$(SRC_MOCK)" "$(DST_MOCK)"
	cp -p "$(SRC_VENV_RUN)" "$(DST_VENV_RUN)"
	cp -p "$(SRC_VENV_RUN_LAUNCH)" "$(DST_VENV_RUN_LAUNCH)"
	ln -sf venv-run.py "$(DST_VENV_RUN_LINK)"
	chmod +x "$(DST_VENV_RUN)" "$(DST_VENV_RUN_LAUNCH)"
	date -u +%Y-%m-%dT%H-%M-%SZ > "$(VERSION)"
	@echo "Updated $(DST_RUN) <- $(SRC_RUN)"
	@echo "Updated $(DST_MOCK) <- $(SRC_MOCK)"
	@echo "Updated $(DST_VENV_RUN) <- $(SRC_VENV_RUN)"
	@echo "Updated $(DST_VENV_RUN_LAUNCH) <- $(SRC_VENV_RUN_LAUNCH)"
	@echo "Linked $(DST_VENV_RUN_LINK) -> venv-run.py"
	@echo "Recorded $(VERSION) $$(cat $(VERSION))"
