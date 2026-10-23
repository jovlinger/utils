# Alpine image: Flask app as non-root user `dmz`. Entry: tini -> start.sh -> run.sh -> python.
#
# Build:
#   docker build -t jovlinger/thermo/dmz .                                   # host-native: TEST/DEV ONLY
#   docker buildx build --platform linux/arm/v6 -t jovlinger/thermo/dmz .    # PRODUCTION (Pi 1B)
#
# !!! ARCHITECTURE NOTE !!!
# Production DMZ image is ARMv6 (Pi 1B). It is built by ../build-and-write.sh, NOT by `make .image`
# in ../Makefile. The Makefile builds host-native on purpose — that image is only used by the test
# stack (thermo/test/dockertest.sh) and by `make runlocal`. Do NOT add `--platform` to the FROM lines
# below, and do NOT change the Makefile to force linux/arm/v6: that would slow down the test loop to
# crawl under QEMU. The production architecture is fixed in build-and-write.sh.
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
COPY requirements.txt strip_charset_normalizer_so.py .
# pydantic<2 still uses pydantic-core; build from source on musl / odd arches when needed.
# charset_normalizer ships mypyc/native *.so wheels; on linux/arm/v6 + musl they can SIGSEGV (see cd.*.so).
# Strip them in this layer (the cross-built image) so Python uses the pure modules - same idea as pip's vendor tree.
# MarkupSafe's musllinux arm wheel is ARM v7-A (_speedups.so) and SIGSEGVs on Pi 1B (armv6).
# setup.py has no skip flag; CC=false fails the compile so it retries a pure-Python build
# (no _speedups.so at all, rather than deleting one after the fact).
RUN pip install --no-cache-dir --break-system-packages --no-binary=pydantic-core -r requirements.txt \
	&& MS_VER="$(python3 -c 'import importlib.metadata as m; print(m.version("markupsafe"))')" \
	&& CC=false pip install --no-cache-dir --break-system-packages --no-binary=markupsafe --force-reinstall --no-deps "markupsafe==${MS_VER}" \
	&& python3 /app/strip_charset_normalizer_so.py \
	&& python3 -c 'import markupsafe, pathlib; root=pathlib.Path(markupsafe.__file__).parent; sos=list(root.rglob("*.so")); assert not sos, sos'

# -----------------------------------------------------------------------------
# Runtime
# -----------------------------------------------------------------------------
FROM alpine:3.19

RUN apk add --no-cache python3 tini su-exec openssl libffi wget \
	&& ln -sf /usr/bin/python3 /usr/bin/python

RUN addgroup -g 1000 dmz \
	&& adduser -D -u 1000 -G dmz dmz

WORKDIR /app

COPY --from=builder /usr/lib/python3.11/site-packages /usr/lib/python3.11/site-packages
# Log wrapper: staged into .docker-import/ before build (see stage-docker-import.sh; source extdeps).
COPY .docker-import/run-with-stdout-logged.py /app/run-with-stdout-logged.py
COPY .docker-import/common /app/common
COPY .docker-import/ui /app/ui
COPY . .
RUN chown -R dmz:dmz /app \
	&& chmod +x /app/start.sh /app/run.sh /app/run-with-stdout-logged.py

ENV PORT=8080
ENV UI_PORT=8090
EXPOSE 8080 8090

USER root
ENTRYPOINT ["/sbin/tini", "--"]
CMD ["/app/start.sh"]
