DMZ Pi 1B — Alpine diskless + Docker-exported root (dmz_rootfs.tar)

Edit install/network.conf on this card (one line: ADDR/CIDR GATEWAY) before first boot if needed.

Boot: firmware loads kernel from this FAT volume; Alpine applies dmz.apkovl.tar.gz; /etc/local.d/dmz-boot.start brings up eth0, extracts dmz_rootfs.tar, chroots into it, runs the same entrypoint as docker run (tini → start.sh → run-with-stdout-logged.py → run.sh → app). Verbose boot steps are appended to /tmp/boot.log on the Pi; app log file lives on chroot tmpfs and /var/log/dmz.log on the host is a symlink there (tail -f /var/log/dmz.log).

Rescue (RAM Alpine, serial or keyboard): `sh /root/sshd.sh` — LAB 192.168.88.x/24; copies `install/rescue_authorized_keys` (same content baked under `/root/install/` until FAT mounts); then starts sshd. Build merges builder `~/.ssh/*.pub` into FAT `install/rescue_authorized_keys`. sshd is off until you run the script.

Prior full Pi pipeline (bwrap, separate tarball workflow) is on git branch overly_complicated_double_pivot.
