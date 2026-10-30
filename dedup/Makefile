# dedup -- content-addressed SHA-256 store (shasrv).
BINLINKS := ../binlinks

.PHONY: binlinks test all-tests

binlinks:
	ln -sf ../dedup/dedup.sh $(BINLINKS)/dedup
	ln -sf ../dedup/cpdup.sh $(BINLINKS)/cpdup
	ln -sf ../dedup/redup.sh $(BINLINKS)/redup
	ln -sf ../dedup/fixdup.sh $(BINLINKS)/fixdup

test:
	@:

all-tests: test
