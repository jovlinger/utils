FROM python:3.11.6-slim

WORKDIR /app
ADD *py requirements.txt

RUN pip install -r requirements.txt

RUN test.sh
