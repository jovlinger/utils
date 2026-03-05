# Pi Zero 2 W: arm64 or armhf. GHCR: ghcr.io/jovlinger/thermo-onboard
#
# Local:  docker build -q -t ghcr.io/jovlinger/thermo-onboard .
# Test:  docker run --rm -it ghcr.io/jovlinger/thermo-onboard sh test.sh

# Platform set by build (arm64 or arm/v7 for 32-bit Pi OS)
FROM python:3.11-slim

WORKDIR /app
# Build deps for cryptography/cffi on armhf (no pre-built wheels)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libffi-dev libssl-dev python3-dev \
    && rm -rf /var/lib/apt/lists/*

# copy everything, including this file... why not?
COPY . .

RUN pip install --no-cache-dir -r requirements.txt

# 5000: app API; 8080: UI
EXPOSE 5000 8080 

CMD ["bash", "./run.sh"]

