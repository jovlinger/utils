# shadup — content-addressed store and ingest pipeline.
BINLINKS := ../binlinks

.PHONY: binlinks

binlinks:
	ln -sf ../shadup/ingest.sh $(BINLINKS)/ingest
	ln -sf ../shadup/postingest $(BINLINKS)/postingest
	ln -sf ../shadup/shadup $(BINLINKS)/shadup
	ln -sf ../shadup/importtags $(BINLINKS)/importtags
