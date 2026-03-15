# DMZ Pi 1B Image

Scripts to create a complete bootable SD image for the DMZ on Raspberry Pi 1B and write it to a memory card.

## Overview

| Script | Purpose |
|--------|---------|
| `create-image.sh` | Build `dmz.img` (Alpine diskless + DMZ app) |
| `write-to-card.sh` | Write the image to an SD card via `dd` |

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

Type `YES` when prompted to confirm.

### 3. Boot the Pi 1B

Insert the SD card and power on. The `dmz-init.start` script runs automatically: entropy, clock sync, iptables redirect (80→8080), and the sandboxed app.

### 4. Verify

```bash
curl http://<pi-ip>/zones
```

## Alternative: prepare-sd.sh

If you already have Alpine on an SD card and prefer to copy files manually, use the install workflow instead:

```bash
./install/export_rootfs.sh jovlinger/thermo/dmz dmz_rootfs.tar
./install/prepare-sd.sh dmz_rootfs.tar /path/to/sd/mount
```

See [install/README.md](../install/README.md) and [plan.md](../plan.md).
