# DMZ logging strategy

Boot log lives on **tmpfs** (`/tmp`). The app log is **`/var/log/dmz.log`** on the host (tmpfs while `/` is RAM root); it is bind-mounted into chroot/bwrap so the same path is used inside the sandbox. Nothing is written to the SD card at runtime except the one-time copy of the boot log (and forensic append of the app log into the boot log snapshot) to `debug/` before unmount.

## Boot log: `/tmp/boot.log`

- Written once by `dmz-init.start` (OpenRC `local.d`).
- Contains: SD discovery, network setup, steps 1–7, forensic dump (mounts, cmdline, dmesg, uname).
- **No rotation.** At the end of boot, the script copies it to `SD_MOUNT/debug/boot.log` (and writes `debug/state.txt`) so the card has a snapshot when pulled.
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
