.image: *py *sh
	docker build -q -t jovlinger/thermo/onboard . > .image

clean:
	# if .image; then
	SHA=$(cat .image)
	docker image rm "${SHA}"
	rm .image
	# fi
