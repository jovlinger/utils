
* run test.sh in a temporary container from image j/t/d. -rm : remove container after
  >  docker run --rm -it jovlinger/thermo/dmz sh test.sh

* run bash in a temporary container
  >  docker run --rm -it jovlinger/thermo/dmz bash
  >  docker run --rm -it --entrypoint bash jovlinger/thermo/dmz 