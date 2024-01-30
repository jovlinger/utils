dockertest: .image
	$(MAKE) -C ../dmz .image
	$(MAKE) -C ../onboard .image
	./dockertest.sh

.image: testcases/*.py *.sh  requirements.txt
	docker build -q -t jovlinger/thermo/test . > .image

clean:
	# if .image; then
	SHA=$(cat .image)
	docker image rm "${SHA}"
	rm .image
	# fi
