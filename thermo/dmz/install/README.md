# Install (SD card contents)

Files here are copied to **`install/`** on the boot FAT by `build-and-write.sh`.

| File | Role |
|------|------|
| `network.conf` | One line: `ADDR/CIDR GATEWAY` (edit on the card before boot if defaults are wrong). |
| `buildinfo.txt` | Written at image build time (build id + git). |
| `dmz-boot.start` | Source for apkovl `/etc/local.d/` (also embedded in `dmz.apkovl.tar.gz` on the card). |
| `root-network-sshd.sh` | Same script as RAM **`/root/network-and-sshd.sh`** (rescue: `192.168.88.200/24` + ssh; keys from build host `~/.ssh/id_rsa.pub`). |
| `CARD-README.txt` | Short human notes; copied to `README.txt` on FAT root. |

Boot diagnostics go to **`/tmp/boot.log`** on the Pi; app output is **`/var/log/dmz.log`** (copies may appear under **`debug/`** on the SD when unmounted cleanly).

Edit **`network.conf`** on the mounted FAT volume if the Pi is not `192.168.1.50/24` with gateway `192.168.1.1`.
