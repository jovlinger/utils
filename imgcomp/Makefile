.PHONY: test all-tests build-ext

VENV_PYTHON := .venv/bin/python
BUILD_STAMP := .venv/.stack_c_built

$(VENV_PYTHON): requirements.txt
	../create_pipenv.sh --sync imgcomp

$(BUILD_STAMP): $(VENV_PYTHON) setup.py imgcomp/_math.pyx imgcomp/_math.pxd imgcomp/affine_simd.c imgcomp/affine_simd.h imgcomp/_stack_c.pyx imgcomp/_stack_c.pxd tests/_stack_bench_c.pyx tests/_math_bench_c.pyx
	$(VENV_PYTHON) setup.py build_ext --inplace
	@touch $(BUILD_STAMP)

build-ext: $(BUILD_STAMP)

test: $(BUILD_STAMP)
	$(VENV_PYTHON) -m pytest -m "not slow"

all-tests: $(BUILD_STAMP)
	$(VENV_PYTHON) -m pytest
