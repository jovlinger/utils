.image: *py *sh  requirements.txt
	docker build -q -t jovlinger/thermo/dmz . > .image

clean:
	# if .image; then
	SHA=$(cat .image)
	docker image rm "${SHA}"
	rm .image
	# fi

test: 
	./test.sh
