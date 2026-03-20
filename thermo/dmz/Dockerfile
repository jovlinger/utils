# Multi-stage build for Pi 1B (ARMv6). Stage 1 builds Python deps (incl. cryptography/Rust);
# stage 2 produces a minimal runtime image.
#
# Usage:
#   docker build -q -t jovlinger/thermo/dmz .
#   docker buildx build --platform linux/arm/v6 -t jovlinger/thermo/dmz --load .
#   docker run --rm -it jovlinger/thermo/dmz sh test.sh

# -----------------------------------------------------------------------------
# Stage 1: Builder (full toolchain for cryptography/Rust)
# -----------------------------------------------------------------------------
FROM alpine:3.19 AS builder

RUN apk add --no-cache \
    python3 py3-pip \
    rust cargo \
    gcc musl-dev libffi-dev openssl-dev python3-dev

WORKDIR /app
COPY requirements.txt .
# Force building pydantic-core from source to avoid accidentally pulling an
# ARMv7-optimized wheel that can SIGILL on ARMv6 at runtime.
RUN pip install --no-cache-dir --break-system-packages --no-binary=pydantic-core -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: Runtime (minimal; no Rust, no build tools)
# -----------------------------------------------------------------------------
FROM alpine:3.19

RUN apk add --no-cache python3 tini openssl libffi \
    && ln -sf /usr/bin/python3 /usr/bin/python

WORKDIR /app
COPY . .

# Copy pre-built site-packages from builder
COPY --from=builder /usr/lib/python3.11/site-packages /usr/lib/python3.11/site-packages

ENV PORT=8080
EXPOSE 8080

ENTRYPOINT ["tini", "--"]
CMD ["sh", "./run.sh"]
