# utils/ — refresh PATH-visible symlinks under binlinks/.
#
#   make binlinks
#
# 1. Links every executable file in this directory (repo root) into binlinks/.
# 2. Runs ``make binlinks`` in each immediate subdirectory (except binlinks/
#    itself, to avoid a recursive loop).

BIN_ROOT := $(abspath .)
BINLINKS_DIR := $(BIN_ROOT)/binlinks

# Immediate child directories that get a sub-make (never binlinks/ or __pycache__).
SUBDIRS := $(filter-out binlinks __pycache__,$(patsubst %/,%,$(wildcard */)))

.PHONY: binlinks binlinks-root $(addprefix binlinks-,$(SUBDIRS))

binlinks: binlinks-root $(addprefix binlinks-,$(SUBDIRS))

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

binlinks-%:
	@$(MAKE) -C $* binlinks
