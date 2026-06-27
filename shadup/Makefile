# shadup — content-addressed store and ingest pipeline.
BINLINKS := ../binlinks

.PHONY: binlinks test all-tests

PYTEST := .venv/bin/pytest

$(PYTEST): requirements.txt
	../create_pipenv.sh --sync shadup

binlinks:
	ln -sf ../shadup/ingest.sh $(BINLINKS)/ingest
	ln -sf ../shadup/postingest $(BINLINKS)/postingest
	ln -sf ../shadup/shadup $(BINLINKS)/shadup
	ln -sf ../shadup/importtags $(BINLINKS)/importtags

test: $(PYTEST)
	$(PYTEST)

all-tests: test
