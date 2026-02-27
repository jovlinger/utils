.PHONY: all clean test

all: .image

.image: Dockerfile requirements.txt $(wildcard *.py) $(wildcard *.sh)
	docker build -q -t jovlinger/thermo/dmz . > .image

clean:
	@[ -f .image ] && docker image rm $$(cat .image) 2>/dev/null || true
	@rm -f .image

test: .image
	./test/run.sh
