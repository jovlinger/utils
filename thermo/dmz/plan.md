# DMZ plan (Docker-first)

## Goal

Run `app.py` in a **plain Alpine container**: predictable dependencies, **non-root** runtime user, minimal custom plumbing.

## Stack

- **OS:** Alpine (musl).
- **Python:** 3.11 from Alpine packages; app deps from `requirements.txt` with **pydantic &lt; 2** to avoid pydantic v2 / extension friction on constrained arches.
- **Process:** `tini` → `start.sh` (root) → `su-exec` → `run-with-stdout-logged.py` → `run.sh` → `python -u app.py`.
- **Hardening (best-effort):** tmpfs on `/tmp` only (not all of `/var/log`, so a bind-mounted `dmz.log` works); optional `mount -o remount,ro /` when the environment allows it.

## Explicit non-goals (in this repo subtree)

- No iptables, bubblewrap, or **bwrap** launcher (replaced by chroot of the Docker-exported rootfs).
- Pi bootable FAT image and **`install/dmz-boot.start`** live here; the heavier legacy layout is on **`overly_complicated_double_pivot`**.

## Operations

Build and run as in [README.md](README.md). Prefer orchestrator-level **`tmpfs`** for `/tmp` over granting `CAP_SYS_ADMIN` when possible; avoid tmpfs-on-all-of-`/var/log` if the log file is bind-mounted.

**Pi 1B:** [build-and-write.sh](build-and-write.sh) builds **`linux/arm/v6`**, **`dmz_rootfs.tar`**, Alpine RPi FAT **`dist/dmz.img`**. Optional **block device** argument: background unmount during the build, then **`sudo dd`**. With no args, image only (no sudo). Fallback: [planC.md](planC.md). Legacy flow: branch **`overly_complicated_double_pivot`**.
