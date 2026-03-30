# Exact Steps: Run DMZ Image on Pi 1B (Raw, No Docker)

This document gives the concrete steps to build the `jovlinger/thermo/dmz` image and run it on a Raspberry Pi 1B without the Docker daemon. Execution uses **bwrap** (Bubblewrap) on Alpine Linux: read-only rootfs, tmpfs for `/tmp`, chroot-like isolation.

## Prerequisites

- **Dev machine**: Docker (or Docker Buildx for cross-compile)
- **Pi 1B**: Alpine Linux diskless (RAM-boot) per PISEC.md / README-dmz.md, with `bubblewrap` installed

## Image Naming

The Makefile uses `jovlinger/thermo/dmz`. For Docker Hub this is `owner/repo`. For GitHub Container Registry (GHCR) use `ghcr.io/jovlinger/thermo-dmz` (or `thermo/dmz`); tag and push accordingly.

---

## Step 1: Build Image for ARMv6 (on dev machine)

Pi 1B uses ARMv6. Cross-build:

```bash
cd thermo/dmz
docker buildx build --platform linux/arm/v6 -t jovlinger/thermo/dmz .
```

For local x86_64 testing only:

```bash
make
# or: docker build -q -t jovlinger/thermo/dmz .
```

---

## Step 2: Export Image to Rootfs Tarball (on dev machine)

```bash
cd thermo/dmz
chmod +x install/export_rootfs.sh install/run_raw.sh
./install/export_rootfs.sh jovlinger/thermo/dmz dmz_rootfs.tar
```

This produces `dmz_rootfs.tar` (or the path you pass as the second argument).

---

## Step 3: Copy Payload to Pi’s SD Card

With the SD card mounted (on your dev machine or via a card reader):

```bash
cp dmz_rootfs.tar /path/to/sd/root/
# e.g. /Volumes/boot/ or /media/mmcblk0p1/
```

Copy the run script as well:

```bash
cp -r thermo/dmz/install /path/to/sd/root/
chmod +x /path/to/sd/root/install/run_raw.sh
```

---

## Step 4: Prepare Alpine on Pi 1B

On the Pi (or in your apkovl / RAM config):

1. Add bwrap to the world file and commit:
   ```bash
   apk add bubblewrap
   lbu commit -d
   ```

2. Ensure `dmz-init.start` (or equivalent) does:
   - iptables redirect: `80 -> 8080`
   - creates unprivileged user if needed
   - launches the app via `run_raw.sh` (see Step 5)

---

## Step 5: Extract and Run on Pi 1B

On the Pi, with the SD root at `/media/mmcblk0p1` (adjust if yours differs):

```bash
# Extract rootfs
mkdir -p /tmp/dmz_rootfs
tar -xf /media/mmcblk0p1/dmz_rootfs.tar -C /tmp/dmz_rootfs

# Run (as unprivileged user if desired)
/media/mmcblk0p1/install/run_raw.sh /tmp/dmz_rootfs
```

For debugging (interactive shell inside the sandbox):

```bash
/media/mmcblk0p1/install/run_raw.sh /tmp/dmz_rootfs --debug
```

---

## Step 6: iptables Redirect (if not in dmz-init.start)

```bash
modprobe iptable_nat
iptables -t nat -A PREROUTING -p tcp --dport 80 -j REDIRECT --to-port 8080
```

The app listens on port 8080; external traffic hits port 80.

---

## Script Reference

| Script | Purpose |
|--------|---------|
| `install/export_rootfs.sh` | Export `jovlinger/thermo/dmz` (or given image) to a rootfs tarball |
| `install/run_raw.sh` | Run extracted rootfs via bwrap (no Docker) |

See `PISEC.md` and `README-dmz.md` for the full architecture and hardening details.
