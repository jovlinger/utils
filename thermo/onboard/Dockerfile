FROM python:3.11.6-slim

WORKDIR /app
ADD *py requirements.txt

RUN pip install -r requirements.txt

# -d means this will fork and exit. FIXME. Add local host:port and remote host:port
RUN python pingpong.py -d 
# need to specify exact port
RUN flask run 
