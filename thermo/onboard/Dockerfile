# use like so. 
# > cd <here>
# > docker build -q -t jovlinger/thermo/onboard .  # add -q for use in emacs, too chatty otherwise
# > docker run --rm -it jovlinger/thermo/onboard sh test.sh # test it

# Pi Zero 2 W: arm64 only (armhf/armv7 not supported)
FROM --platform=linux/arm64 python:3.11-slim

WORKDIR /app
# copy everything, including this file... why not?
COPY . . 

RUN pip install --no-cache-dir -r requirements.txt

# need to specify exact port. 5000 is default in app.py
EXPOSE 5000 

CMD ["bash", "./run.sh"]

