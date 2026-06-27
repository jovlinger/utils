.PHONY: test all-tests

PYTEST := .venv/bin/pytest

$(PYTEST): requirements-dev.txt
	../create_pipenv.sh --sync vox2stl

test: $(PYTEST)
	$(PYTEST)

all-tests: test

# Legacy alias.
testall: all-tests
