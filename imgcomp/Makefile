.PHONY: test all-tests build-ext

VENV_PYTHON := .venv/bin/python
EXT_SUFFIX := $(shell $(VENV_PYTHON) -c "import sysconfig; print(sysconfig.get_config_var('EXT_SUFFIX'))" 2>/dev/null)
MATH_EXT := imgcomp/_math$(EXT_SUFFIX)
PAINT_EXT := imgcomp/_paint$(EXT_SUFFIX)

$(VENV_PYTHON): requirements.txt
	../create_pipenv.sh --sync imgcomp

build-ext: $(VENV_PYTHON) imgcomp/_math.pyx imgcomp/_paint.pyx setup.py
	$(VENV_PYTHON) setup.py build_ext --inplace

$(MATH_EXT): build-ext
$(PAINT_EXT): build-ext

test: $(VENV_PYTHON) $(MATH_EXT) $(PAINT_EXT)
	$(VENV_PYTHON) -m pytest -m "not slow"

all-tests: $(VENV_PYTHON) $(MATH_EXT) $(PAINT_EXT)
	$(VENV_PYTHON) -m pytest
