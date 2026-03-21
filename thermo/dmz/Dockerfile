# Alpine image: Flask app as non-root user `dmz`. Entry: tini -> start.sh -> run.sh -> python.
#
# Build:
#   docker build -t jovlinger/thermo/dmz .
#   docker buildx build --platform linux/arm/v6 -t jovlinger/thermo/dmz --load .
#
# Run (optional --tmpfs /tmp; do not tmpfs over all of /var/log if you bind-mount dmz.log):
#   docker run --rm -p 8080:8080 jovlinger/thermo/dmz
# ENTRYPOINT is only tini; default CMD is start.sh. A trailing command replaces CMD:
#   docker run --rm -it jovlinger/thermo/dmz /bin/sh   ->  tini -- /bin/sh

# -----------------------------------------------------------------------------
# Builder: compile wheels that need a toolchain (cryptography, pydantic-core on musl).
# -----------------------------------------------------------------------------
FROM alpine:3.19 AS builder

RUN apk add --no-cache \
	python3 py3-pip \
	rust cargo \
	gcc musl-dev libffi-dev openssl-dev python3-dev

WORKDIR /app
COPY requirements.txt .
# pydantic<2 still uses pydantic-core; build from source on musl / odd arches when needed.
RUN pip install --no-cache-dir --break-system-packages --no-binary=pydantic-core -r requirements.txt

# -----------------------------------------------------------------------------
# Runtime
# -----------------------------------------------------------------------------
FROM alpine:3.19

RUN apk add --no-cache python3 tini su-exec openssl libffi \
	&& ln -sf /usr/bin/python3 /usr/bin/python

RUN addgroup -g 1000 dmz \
	&& adduser -D -u 1000 -G dmz dmz

WORKDIR /app

COPY --from=builder /usr/lib/python3.11/site-packages /usr/lib/python3.11/site-packages
# Log wrapper: staged into .docker-import/ before build (see stage-docker-import.sh; source bin repo).
COPY .docker-import/run-with-stdout-logged.py /app/run-with-stdout-logged.py
COPY . .
RUN chown -R dmz:dmz /app \
	&& chmod +x /app/start.sh /app/run.sh /app/run-with-stdout-logged.py

ENV PORT=8080
EXPOSE 8080

USER root
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/app/start.sh"]
