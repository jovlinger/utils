BINLINKS := ../binlinks

.PHONY: binlinks test all-tests test-taskevent

binlinks:
	mkdir -p $(BINLINKS)
	ln -sf ../spinme/host/scripts/spinmecli $(BINLINKS)/spinmecli

# Fast suite: Python TaskEvent SoT + host C tests when present.
test: test-taskevent
	$(MAKE) -C host test

test-taskevent:
	cd "$(CURDIR)" && PYTHONPATH=. detest --runner=unittest taskevent/test_taskevent.py
	cd "$(CURDIR)" && PYTHONPATH=. ./taskevent/gen_c_header.py --check

all-tests: test
