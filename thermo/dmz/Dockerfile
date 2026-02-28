# use like so.
# > cd <here>
# > docker build -q -t jovlinger/thermo/dmz .
# For Pi 1B (ARMv6): docker buildx build --platform linux/arm/v6 -t jovlinger/thermo/dmz .
# > docker run --rm -it jovlinger/thermo/dmz sh test.sh
#
# Minimal Alpine base per plan.md: lightweight, ARMv6-compatible.
# To run without Docker daemon on Pi 1B, use install/run_raw.sh.

FROM alpine:3.19

RUN apk add --no-cache python3 py3-pip tini && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app
# copy everything, including this file... why not?
COPY . . 

RUN pip install --no-cache-dir -r requirements.txt

# App listens on 8080 (unprivileged); iptables redirects 80->8080 on host.
ENV PORT=8080
EXPOSE 8080

# tini as PID 1 reaps zombies in bwrap sandbox
ENTRYPOINT ["tini", "--"]
CMD ["sh", "./run.sh"]

