# Fast MPD dont-walk / .mpdignore contract tests (stdlib unittest).
# Root `make test` includes this dir via the */Makefile wildcard.

.PHONY: binlinks test all-tests

binlinks:
	@:

test:
	python3 -m unittest discover -s . -p 'test_*.py' -v

all-tests: test
