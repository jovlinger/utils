# use like so. 
# > cd <here>
# > docker build -q -t jovlinger/thermo/test .  # add -q for use in emacs, too chatty otherwise
# > docker run --rm -it jovlinger/thermo/test sh test.sh # test it

FROM python:3.11.6-slim

WORKDIR /app
# copy everything, including this file... why not?
COPY . . 

RUN pip install --no-cache-dir -r requirements.txt

# need to specify exact port. 5000 is default in app.py
EXPOSE 5000 

CMD ["bash", "./test.sh"]
