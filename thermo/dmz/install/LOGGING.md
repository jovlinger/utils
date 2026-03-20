# DMZ logging strategy

Boot log lives on **tmpfs** (`/tmp`). The app log is **`/var/log/dmz.log`** on the host (tmpfs while `/` is RAM root); it is bind-mounted into chroot/bwrap so the same path is used inside the sandbox. The SD card is written only when **`/root/dmz-forensics.sh`** runs: it **umounts** `/media/mmcblk0`, **remounts** `/dev/mmcblk0`, then **overwrites** `debug/forensics.txt`, `debug/boot.log`, `debug/dmz.log`, and `debug/state.txt`, and **umounts** again. `dmz-init` invokes that at step **12/12**; you can run the same script anytime over SSH (host root only, not inside bwrap).

## Boot log: `/tmp/boot.log`

- Written once by `dmz-init.start` (OpenRC `local.d`).
- Contains: SD discovery, network, iptables, launch, step 10 runtime checkpoint (mounts, ip, listeners, filtered processes), and stdout from **`dmz-forensics.sh`**.
- **No rotation.** Latest SD snapshot: **`debug/boot.log`** is overwritten each time **`dmz-forensics.sh`** runs (includes the full `/tmp/boot.log` at that moment). Deep dive: **`debug/forensics.txt`** (full `dmz.log`, tail of boot log, `iptables-save`, `ps`, etc.).
- On the running Pi, the live log is always `/tmp/boot.log`. See BOOT-LOG-TREE.md for how to use it for debugging.

## App log: `/var/log/dmz.log`

- The app is started via **run-with-stdout-logged.py** (in the container image). It runs `python app.py` and appends its stdout/stderr to **`/var/log/dmz.log`** (same path in chroot/bwrap via bind mount from the host).
- **Rotation:** when the current log file exceeds **1 MB**, it is renamed to `dmz.log.<isodatetime>` and a new empty `dmz.log` is used. After each rotation, if total size of all `dmz.log.<timestamp>` files exceeds **2 MB**, oldest rotated files are deleted until total ≤ 2 MB.
- **Mechanism:** `install/run_raw.sh` invokes `python run-with-stdout-logged.py /var/log/dmz.log 1048576 2097152 sh ./run.sh`.

## Summary

| Log   | Path           | Rotation                         | When written        |
|-------|----------------|-----------------------------------|---------------------|
| Boot  | `/tmp/boot.log`  | None                             | Once at boot        |
| App   | `/var/log/dmz.log` | 1 MB file → rotate; 2 MB rotated total cap | run-with-stdout-logged.py |
