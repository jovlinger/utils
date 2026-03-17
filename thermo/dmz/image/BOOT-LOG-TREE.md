# Boot log: decision tree and contingencies

The script writes to **/root/boot.log** only. The SD card is read-only; root (/) is tmpfs and writable. So the log is always at **/root/boot.log**. After you bring up net (e.g. run network-and-sshd.sh), scp it off: `scp root@<pi-ip>:/root/boot.log .`

The log is detailed: every step, SD discovery (each path tried), network.conf read, ip addr/route/resolv dumps, and a full forensic dump (mounts, cmdline, dmesg filter, uname) at the end.

---

## Tree: what we log and what we do when it's not as expected

### 0. Script runs
- **Log:** `dmz-init started`
- **Hope:** This line appears in the log → script was invoked by OpenRC.
- **Else:** No log file (or file empty / stale) → script didn't run or exited before first pr(). Check overlay applied: `ls /etc/local.d/` on Pi.

### 1. SD_MOUNT discovery
- **Log:** For each path we try: found or missing; then SD_MOUNT and source. Plus ls of SD_MOUNT and install/, first line of network.conf and buildinfo.
- **Hope:** One of /media/mmcblk0, /media/mmcblk0p1, /boot, /mnt/mmcblk0p1 has our files, or we find it in /proc/mounts.
- **Else:** fallback /media/mmcblk0; we still dump ls so you see what's there.

### 2. Banner / buildinfo
- **Log:** buildinfo line or `dmz-init (no buildinfo)`, `SD: <SD_MOUNT>`, `local <date>`
- **Else:** no buildinfo → buildinfo.txt missing at SD_MOUNT/install/buildinfo.txt (wrong path or image).

### 4. Network: eth0 exists?
- **Log:** `eth0 found (after Ns)` or `eth0 not found after 20s, skipping`
- **Hope:** eth0 found within 20s.
- **Else:** not found → we log "eth0 not found after 20s"; no IP. Driver or interface naming issue.

### 5. Network: network.conf
- **Log:** `no <path>/network.conf` or `network.conf empty or unreadable` or we proceed to addr/gw.
- **Hope:** file exists and read gives addr and gw.
- **Else:** we log the missing/empty case; no IP.

### 6. Network: ip addr add
- **Log:** `added <addr>` or `ip addr add <addr> failed (may already exist)`
- **Else:** failed → we still log it; NET_OK=1 so we continue (might already exist).

### 7. Network: ip route add
- **Log:** `default via <gw>` or `ip route add default via <gw> failed`
- **Else:** failed → we log it; no default route.

### 8. Steps 1/7–6/7 (entropy, clock, iptables, adduser, rootfs, app)
- **Log:** each step name; rootfs/app failures would exit script (set -e) and last line in log is the step that failed.
- **Contingency:** If log ends before "dmz-init complete", the last line is where it died.

### 9. Unmount
- **Log:** `dmz-init complete`. Log is in /root/boot.log (tmpfs); scp it off after bringing up net.

---

## Where to read the log

- **On the Pi:** `cat /root/boot.log` (or after bringing up net: `scp root@<pi-ip>:/root/boot.log .` from your Mac).

---

## What’s in the log (and forensic)

| Section | Expectation | What is recorded when not as expected |
|--------|-------------|--------------------------------------|
| 1. Boot partition | Mounted at a known path | SD_MOUNT, source (fixed/proc_mounts/fallback), path exists?, ls of SD root |
| 2. install/ | Directory with network.conf, buildinfo, scripts | install/ missing? ls of install/ |
| 3. network.conf | One line ADDR GATEWAY | File missing? First line and parsed addr/gw; notes if empty |
| 4. buildinfo.txt | Present with build ID | Missing? Content or "(read failed)" |
| 5. Network interfaces | eth0 exists | List of /sys/class/net; eth0 missing? ip link/addr for eth0 if present |
| 6. Routing | default via GATEWAY | Full ip route output |
| 7. Mounts | — | Full /proc/mounts |
| 8. Kernel cmdline | — | /proc/cmdline |
| 9. dmesg | — | Filtered for mount/overlay/eth/smc/usb/network (last 80) |
| 10. uname | — | uname -a |

Use this to see exactly what the system looked like at the end of dmz-init and why any step did not match expectations.
