# Aggregate build/test across zones. Deploy one zone: make -C zones/<zone> deploy
ZONES := kitchen office bedroom

.PHONY: all build clean test deploy

all: build

build clean test:
	@for zone in $(ZONES); do \
		echo "[zones] $$zone $@"; \
		$(MAKE) -C $$zone $@ || exit $$?; \
	done

deploy:
	@echo "Deploy one zone: make -C zones/<zone> deploy"
	@exit 1
