# DMZ

DMZ is the part of the application which handles access to the internet at large. It has zero credentials, functioning only as an intermediate scratch-pad for rendezvous between the interior zones and the controller.

## How It Works

1. **Zones** (interior, one RPi+ANAVI hat per zone) POST their state to an endpoint. In reply, they receive the most recent command for that zone (and when it was issued).

2. **Controller** (eventually 3rd-party authed client) POSTs commands for each zone and receives the most recent state in reply.

3. The same object with a command slot and sensor slot is used for both; zones can post their own commands and the client can spoof temp settings. (Easy to fix later.)

## Software in This Repo

| Item | Purpose |
|------|---------|
| `app.py` | Flask API for zone state/command rendezvous |
| `Dockerfile` | Alpine-based image with Python, Flask, pydantic |
| `install/export_rootfs.sh` | Export Docker image to rootfs tarball |
| `install/run_raw.sh` | Run extracted rootfs via bwrap (no Docker daemon) |
| `install/prepare-sd.sh` | Copy payload and scripts to SD from dev machine |
| `install/dmz-init.start` | OpenRC boot script template for Pi |
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

```bash
# 1. Build image (ARMv6 for Pi 1B)
cd thermo/dmz
docker buildx build --platform linux/arm/v6 -t jovlinger/thermo/dmz .

# 2. Export rootfs
./install/export_rootfs.sh jovlinger/thermo/dmz dmz_rootfs.tar

# 3. Prepare SD card (with SD mounted at SD_MOUNT)
./install/prepare-sd.sh dmz_rootfs.tar /path/to/sd

# 4. Boot Pi; dmz-init.start runs automatically, or manually:
#    mkdir -p /tmp/dmz_rootfs && tar -xf /media/mmcblk0p1/dmz_rootfs.tar -C /tmp/dmz_rootfs
#    ./install/run_raw.sh /tmp/dmz_rootfs
```

See [plan.md](plan.md) for the full development roadmap and deployment details.
