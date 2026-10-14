.PHONY: binlinks test all-tests

binlinks:
	@:

.venv/bin/pytest: requirements.txt requirements-dev.txt
	cd "$(abspath ..)" && unset VIRTUAL_ENV && ./create_pipenv.sh --sync spinme

test: .venv/bin/pytest
	.venv/bin/pytest

all-tests: test
