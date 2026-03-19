# DMZ

DMZ is the part of the application which handles access to the internet at large. It has zero credentials, functioning only as an intermediate scratch-pad for rendezvous between the interior zones and the controller.

## How It Works

1. **Zones** (interior, one RPi+ANAVI hat per zone) POST their state to an endpoint. In reply, they receive the most recent command for that zone (and when it was issued).

2. **Controller** (eventually 3rd-party authed client) POSTs commands for each zone and receives the most recent state in reply.

3. The same object with a command slot and sensor slot is used for both; zones can post their own commands and the client can spoof temp settings. (Easy to fix later.)

## Software in This Repo

| Item | Purpose |
| ---- | ------- |
| `app.py` | Flask API for zone state/command rendezvous |
| `Dockerfile` | Alpine-based image with Python, Flask, pydantic |
| `install/run_raw.sh` | Run extracted rootfs via bwrap (no Docker daemon) |
| `install/dmz-init.start` | OpenRC boot script template for Pi |
| `image/create-image.sh` | Build complete bootable dmz.img for dd |
| `image/write-to-card.sh` | Write dmz.img to SD card |
| `image/build-and-write.sh` | One-step clean-git + build + write loop |
| `test/` | Tests |

## Hardware (Elsewhere)

The target deployment is a Raspberry Pi 1B running Alpine Linux diskless (RAM boot). Provisioning, SD layout, and apkovl configuration are documented in [plan.md](plan.md).

## Runtime Model

- **Host**: Alpine Linux diskless (RAM boot)
- **Sandbox**: bwrap (Bubblewrap) for app isolation; read-only rootfs, tmpfs for `/tmp`
- **Network**: App listens on port 8080; iptables redirects 80→8080
- **Storage**: No durable writable storage; RO ramdisk; SD unmounts completely after boot and unshare start

## SSH Model

- SSH is **not** started at boot. Start it manually from the physical console when needed.
- **Console**: Password login allowed (physical terminal only).
- **SSH**: Key-only authentication; `PasswordAuthentication no`.

## Quick Start

**Image workflow (recommended):** Create a complete bootable image and write to SD:

```bash
cd thermo/dmz/image
./create-image.sh
./write-to-card.sh dmz.img /dev/sdX   # replace sdX with your SD device
# Boot Pi; dmz-init runs automatically
```

See [plan.md](plan.md) and [image/README.md](image/README.md) for details. For where each install file ends up (overlay vs SD vs rootfs), see [install/README.md](install/README.md#name--path-correspondences). Legacy manual scripts and cloud docs were moved to `thermo/consumed`.
