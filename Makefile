# utils/ — umbrella make targets for the whole tree.
#
#   make binlinks   — refresh PATH-visible symlinks under binlinks/
#   make index      -- rebuild README.md from **/.www/blurb.md
#   make test       — fast tests in every immediate subdir with a Makefile
#   make all-tests  — full suites (docker, e2e, integration) where defined
#
# Convention (every utils/*/Makefile):
#   test       — default, cheap: host/unit pytest, no docker or e2e
#   all-tests  — everything: test + docker builds, compose stacks, e2e, etc.
#   test-local / test-docker — optional building blocks (thermo/); not invoked
#   from the repo root. testall and test_e2e are legacy aliases for all-tests.
#
# Do not list test-<dir> / binlinks-<dir> as prerequisites of test / binlinks:
# GNU make treats those names as empty phony targets and skips the pattern rules.

BIN_ROOT := $(abspath .)
BINLINKS_DIR := $(BIN_ROOT)/binlinks

# Immediate child dirs that contain a Makefile (not binlinks/ itself).
MAKE_SUBDIRS := $(filter-out binlinks,$(patsubst %/Makefile,%,$(wildcard */Makefile)))

.PHONY: binlinks binlinks-root index test all-tests

index:
	@./lib/build-index.py

binlinks: binlinks-root
	@set -e; \
	for dir in $(MAKE_SUBDIRS); do \
	  echo "==> $$dir binlinks"; \
	  $(MAKE) -C $$dir binlinks; \
	done

test:
	@set -e; \
	for dir in $(MAKE_SUBDIRS); do \
	  echo "==> $$dir test"; \
	  $(MAKE) -C $$dir test; \
	done

all-tests:
	@set -e; \
	for dir in $(MAKE_SUBDIRS); do \
	  echo "==> $$dir all-tests"; \
	  $(MAKE) -C $$dir all-tests; \
	done

# Symlink repo-root executables: binlinks/<name> -> ../<file>
# Strip a single .py / .sh / .as suffix from the command name.
binlinks-root:
	@mkdir -p "$(BINLINKS_DIR)"
	@set -e; \
	for f in "$(BIN_ROOT)"/*; do \
	  [ -f "$$f" ] || continue; \
	  [ -x "$$f" ] || continue; \
	  base=$$(basename "$$f"); \
	  case "$$base" in \
	    create_pipenv.sh|setup-venv.sh|mock_cmd.py|*~) continue ;; \
	  esac; \
	  name="$$base"; \
	  case "$$name" in *.py) name=$${name%.py} ;; esac; \
	  case "$$name" in *.sh) name=$${name%.sh} ;; esac; \
	  case "$$name" in *.as) name=$${name%.as} ;; esac; \
	  ln -sf "../$$base" "$(BINLINKS_DIR)/$$name"; \
	done
