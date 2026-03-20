# DMZ Pi 1B Image

Scripts to create a complete bootable SD image for the DMZ on Raspberry Pi 1B and write it to a memory card.

## Overview

| Script | Purpose |
| ------ | ------- |
| `create-image.sh` | Build `dmz.img` (Alpine diskless + DMZ app) |
| `write-to-card.sh` | Write the image to an SD card via `dd` |
| `build-and-write.sh` | Single command: clean-git check, build, then write |

## Prerequisites

- **Docker** — for building the ARMv6 image and fetching apk packages
- **create-image.sh** additionally needs:
  - `mkfs.vfat` (dosfstools) — create FAT32 filesystem
  - `mcopy`, `mmd` (mtools) — copy files into the image without root  
    Or: Linux with `losetup`/`mount` or macOS with `hdiutil` (requires sudo)

On macOS, install tools via Homebrew:

```bash
brew install mtools dosfstools
```

## Workflow

### 1. Create the image

```bash
cd thermo/dmz/image
./create-image.sh
```

Options:

- `--output FILE` — Output path (default: `dmz.img` in script dir)
- `--alpine-version VER` — Alpine version (default: 3.23.3)
- `--size MB` — Image size in MB (default: 256)

### 2. Write to SD card

Insert the SD card and identify the device (e.g. `/dev/sdb`, `/dev/mmcblk0`).

```bash
./write-to-card.sh dmz.img /dev/sdX
```

### One-step build + write

If you want the full loop in one command (and to avoid card/repo drift), use:

```bash
./build-and-write.sh /dev/rdisk4 --output /tmp/dmz-test.img
```

This script:

- Asserts git working tree is clean (so image metadata has a real commit SHA)
- Starts SD-card unmount in the background while image build runs
- Builds via `create-image.sh`
- Waits for unmount completion and then writes image via `write-to-card.sh` (with `sudo`)

### 3. Boot the Pi 1B

Insert the SD card and power on. The `dmz-init.start` script runs automatically: entropy, clock sync, iptables redirect (80→8080), and the sandboxed app.

**Boot timeline:** There is a quiet period (initramfs: kernel, mount overlay, switch_root) with nothing visible on console. Once OpenRC starts, you get a login prompt within about 4 seconds.

**Boot output:** You should see a clear `========== DMZ ==========` block with build hash and local time; then `dmz-init: 1/12` through `12/12` (SD discovery, banner, network, … launch, runtime checkpoint, then **`/root/dmz-forensics.sh`** overwriting `debug/*` on the card), and finally `========== dmz-init complete ==========`. **Clock skew warnings** from OpenRC at the start of boot are expected (Pi has no RTC); time is corrected once dmz-init runs NTP.

### 4. Verify

```bash
curl http://<pi-ip>/zones
```

### Manual network + SSH (console only)

Put your public key in the image at build time: **install/authorized_keys** (one line, your `id_rsa.pub`). The image will contain that single key in `/root/.ssh/authorized_keys`.

On the Pi (root console): `sh /root/network-and-sshd.sh` — brings up eth0 at 192.168.88.200 and starts sshd. Then from your Mac: `ssh root@192.168.88.200`.

See [install/README.md](../install/README.md) and [plan.md](../plan.md).

## Debugging boot (no guessing)

After boot on the Pi, use **[BOOT-DEBUG.md](BOOT-DEBUG.md)** to:

1. Confirm which image is on the card (`BUILD.txt` on the FAT partition).
2. Capture initramfs messages (`dmesg`) to see whether the boot media and overlay were loaded.
3. Check hostname and `/etc/local.d/` to see if the overlay was applied.

Use the exact commands there and share the output so we can fix overlay loading step by step.
