.PHONY: test all-tests

VENV_PYTHON := .venv/bin/python

# Fast check-vox unit tests only; full mesh/STL generation lives in test_vox2stl.py (slow).
FAST_TESTS := test_check_vox_small_examples.py test_check_vox_up_side_examples.py

$(VENV_PYTHON): requirements-dev.txt
	../create_pipenv.sh --sync vox2stl

test: $(VENV_PYTHON)
	$(VENV_PYTHON) -m pytest $(FAST_TESTS) -q

all-tests: $(VENV_PYTHON)
	$(VENV_PYTHON) -m pytest

# Legacy alias.
testall: all-tests
