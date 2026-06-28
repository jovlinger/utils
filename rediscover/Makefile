.PHONY: binlinks test all-tests

PYTEST := .venv/bin/python

$(PYTEST): requirements-dev.txt requirements.txt
	../create_pipenv.sh --sync rediscover

binlinks:
	@:

test: $(PYTEST)
	$(PYTEST) -m pytest tests/

all-tests: test
	./e2e/run_e2e.sh
