.PHONY: dockertest test_e2e clean

# Builds thermo/dmz + onboard GHCR-tagged images (../onboard make images) + testdriver, then docker compose up.
dockertest: .image
	$(MAKE) -C ../onboard images
	$(MAKE) -C ../dmz .image
	./dockertest.sh

.image: testcases/*.py *.sh  requirements.txt
	docker build -q -t jovlinger/thermo/test . > .image

clean:
	# if .image; then
	SHA=$(cat .image)
	docker image rm "${SHA}"
	rm .image
	# fi
