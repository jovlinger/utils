# Plan C — Raspberry Pi OS Lite on Pi 1B (documented fallback)

If the Alpine + `dmz_rootfs.tar` + chroot path (`build-and-write.sh`) is not acceptable, use **Raspberry Pi OS Lite** as the base on the SD card and install the application **on the Pi** with network.

## Target

- **Image:** Raspberry Pi OS Lite **6.1** (or current naming for Pi 1B / armhf “legacy” where applicable).
- **Where:** Flash the official image to the card on a desktop; first boot on Pi with Ethernet (or pre-seeded `wpa_supplicant` if you use Wi‑Fi).

## Deliverable (to be added later)

A single **install tarball** (or unpacked directory) you copy to the Pi and run once as root (or with sudo), which:

1. Runs **`apt update`** / **`apt install`** for OS packages: **`python3`**, **`python3-venv`**, **`python3-pip`**, **`git`**, and build deps for **`cryptography`** (OpenSSL headers, gcc, etc.) as required by that OS.
2. **`git clone`** (or copies) this repo or **`thermo/dmz`** only.
3. Creates a **venv**, **`pip install -r requirements.txt`** with **`pydantic<2`** unchanged.
4. Installs a **systemd** (or rc.local) unit that runs the app entry you choose (`start.sh` / `run.sh` / `gunicorn` — to be decided when implementing).

## Fidelity

This path is **glibc** + Debian packages, not **Alpine musl** + the Docker image root. You get a working service on the Pi, not byte-identical binaries with `docker run` on Alpine.

## Reference branch

The older Alpine diskless + bwrap + `dmz-init` flow lives on **`overly_complicated_double_pivot`**.
