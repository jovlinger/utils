.PHONY: test all-tests build-ext global-warming bench bench-render bench-stack

VENV_PYTHON := .venv/bin/python
BUILD_STAMP := .venv/.stack_c_built
GLOBAL_WARMING_STAMP := .venv/.global_warming
WARM_DEPS := tests/global_warming.py tests/bench_render.py tests/bench_stack_run.py

$(VENV_PYTHON): requirements.txt
	../create_pipenv.sh --sync imgcomp

$(BUILD_STAMP): $(VENV_PYTHON) setup.py imgcomp/_math.pyx imgcomp/_math.pxd imgcomp/affine_simd.c imgcomp/affine_simd.h imgcomp/_stack_c.pyx imgcomp/_stack_c.pxd imgcomp/_stacklang_render_c.pyx tests/_stack_bench_c.pyx tests/_math_bench_c.pyx tests/_simpletest_c.pyx
	$(VENV_PYTHON) setup.py build_ext --inplace
	@touch $(BUILD_STAMP)

$(GLOBAL_WARMING_STAMP): $(BUILD_STAMP) $(WARM_DEPS)
	$(VENV_PYTHON) tests/global_warming.py
	@touch $(GLOBAL_WARMING_STAMP)

build-ext: $(BUILD_STAMP) $(GLOBAL_WARMING_STAMP)

global-warming: $(GLOBAL_WARMING_STAMP)

bench-render: $(GLOBAL_WARMING_STAMP)
	$(VENV_PYTHON) tests/bench_render.py --repeat 3 --warmup 0 --output demo-output-bench

bench-stack: $(GLOBAL_WARMING_STAMP)
	$(VENV_PYTHON) tests/bench_stack_run.py --repeat 3 --output demo-output-bench-stack

bench: bench-render bench-stack

test: $(BUILD_STAMP)
	$(VENV_PYTHON) -m pytest -m "not slow"

all-tests: $(BUILD_STAMP)
	$(VENV_PYTHON) -m pytest
