.PHONY: test all-tests

VENV_PYTHON := .venv/bin/python

$(VENV_PYTHON): requirements.txt
	../create_pipenv.sh --sync imgcomp

test: $(VENV_PYTHON)
	$(VENV_PYTHON) -m pytest

all-tests: test
