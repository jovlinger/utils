test: 
	$(MAKE) -C ../dmz .image
	$(MAKE) -C ../onboard .image
	$(MAKE) -C . .image
	./test.sh

.image: *.py *.sh
	docker build -q -t jovlinger/thermo/test .
	touch .image
