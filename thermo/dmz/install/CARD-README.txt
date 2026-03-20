DMZ Pi 1B SD card (PIBOOT)

This card boots Alpine diskless (RAM root) and runs the DMZ app in a bwrap sandbox.

Three-stage boot (high level)

1) Firmware + initramfs (quiet)
   - Raspberry Pi firmware loads kernel + initramfs from this FAT partition.
   - Alpine initramfs mounts the boot media and unpacks the apkovl overlay.
   - This stage is mostly silent on console.

2) dmz-init (OpenRC local.d) sets up the host
   - Script: /etc/local.d/dmz-init.start
   - Reads install/network.conf from the SD and configures eth0 + default route + resolv.conf
   - Starts haveged (entropy)
   - Syncs time (busybox ntpd)
   - Extracts dmz_rootfs.tar into /tmp/dmz_rootfs (tmpfs)
   - Runs DMZ unit tests inside the sandbox and appends results to /tmp/boot.log
   - Launches the app in background via install/run_raw.sh
   - Copies /tmp/boot.log to debug/boot.log on the card, then unmounts the SD

3) App runtime (bwrap “container-lite”)
   - Launcher: install/run_raw.sh
   - bwrap runs the extracted rootfs as read-only / with tmpfs /tmp
   - App is started via run-with-stdout-logged.py, which writes stdout/stderr to /var/log/dmz.log

Logs
  - Boot: /tmp/boot.log (also copied to debug/boot.log on the card at end of boot)
  - App:  /var/log/dmz.log (rotated by run-with-stdout-logged.py; host path bind-mounted in sandbox)

Files on this partition
  - dmz_rootfs.tar      : exported container root filesystem (payload)
  - dmz.apkovl.tar.gz   : overlay applied at boot (includes dmz-init + keys + helpers)
  - install/            : scripts and config read by dmz-init
  - debug/              : written by dmz-init (boot.log snapshot + state.txt)

