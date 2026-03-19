# Install Scripts

Order of operations: **build image → flash → boot → test**

| Step | Script | Where |
| ---- | ------ | ----- |
| 1. Build image | `cd ../image && ./create-image.sh --output /tmp/dmz-test.img` | Dev machine |
| 2. Write SD | `cd ../image && ./write-to-card.sh /tmp/dmz-test.img /dev/sdX` | Dev machine |
| 3. Boot | dmz-init.start runs automatically | Pi 1B |
| 4. Or manual | `./run_raw.sh /tmp/dmz_rootfs` | Pi 1B (after extract) |

See [plan.md](../plan.md) for dmz-init.start setup (lbu, apkovl).

## Name / path correspondences

Where repo files end up on the running Pi or on the SD card.

### Overlay (apkovl) on the running Pi

| Repo | On Pi |
| ---- | ----- |
| `install/root-network-sshd.sh` | `/root/network-and-sshd.sh` |
| `install/network.conf` | `/root/network.conf` |
| `install/dmz-init.start` | `/etc/local.d/dmz-init.start` |
| `~/.ssh/id_rsa.pub` | `/root/.ssh/authorized_keys` |

### SD card

All of `install/*` is copied to the card as `install/<basename>` (e.g. `install/run_raw.sh` → SD `install/run_raw.sh`).

### Rootfs (container image)

- `dmz/run.sh` lives in the Docker image as `/app/run.sh`. Extracting `dmz_rootfs.tar` gives e.g. `/tmp/dmz_rootfs/app/run.sh` — same name, inside the rootfs.
- `install/run_raw.sh` is the bwrap launcher; it lives only on the SD at `install/run_raw.sh`, not inside the rootfs tarball.
