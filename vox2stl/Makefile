.PHONY: test testall

PYTEST := .venv/bin/pytest

$(PYTEST): requirements-dev.txt
	../create_pipenv.sh --sync vox2stl

test: $(PYTEST)
	$(PYTEST)

testall: test
