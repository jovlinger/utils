# skills/ — umbrella for skill packages that ship their own tooling.
# Only projectmanagement/todos has a Makefile so far; add more subdirs here
# as they grow binlinks or tests of their own.

.PHONY: binlinks test all-tests

binlinks:
	$(MAKE) -C projectmanagement/todos binlinks

test:
	$(MAKE) -C projectmanagement/todos test

all-tests:
	$(MAKE) -C projectmanagement/todos all-tests
