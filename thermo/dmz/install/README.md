# Install (SD card contents)

Files here are copied to **`install/`** on the boot FAT by `build-and-write.sh`.

## Stable rescue SSH host keys (not in git)

Pi rescue **`sshd`** (after **`sh /root/network-and-sshd.sh`**) should keep the **same host keys** across SD images so your laptop’s **`known_hosts`** does not warn on every flash.

- **Directory:** **`../.secrets/ssh-host/`** (listed in **`../.gitignore`**).
- **Generate once per clone** (or copy `.secrets/` between machines if you want identical keys):

  ```bash
  cd thermo/dmz
  chmod +x install/gen-dmz-rescue-host-keys.sh   # if needed
  ./install/gen-dmz-rescue-host-keys.sh
  ```

- **`build-and-write.sh`** copies **`ssh_host_ed25519_*`** and **`ssh_host_rsa_*`** into the apkovl as **`/etc/ssh/`**. If keys are missing, the build runs the generator, then copies them.

**Security:** treat **`../.secrets/`** like private material (backup if you care, never commit).

| File | Role |
|------|------|
| `network.conf` | One line: `ADDR/CIDR GATEWAY` (edit on the card before boot if defaults are wrong). |
| `buildinfo.txt` | Written at image build time (build id + git). |
| `dmz-boot.start` | Source for apkovl `/etc/local.d/` (also embedded in `dmz.apkovl.tar.gz` on the card). |
| `root-network-sshd.sh` | Same script as RAM **`/root/network-and-sshd.sh`** (rescue: `192.168.88.200/24` + sshd pubkey-only; keys merged at build from `~/.ssh/id_{ed25519,ecdsa,rsa}.pub`). |
| `CARD-README.txt` | Short human notes; copied to `README.txt` on FAT root. |

Boot diagnostics go to **`/tmp/boot.log`** on the Pi; app output is **`/var/log/dmz.log`** (copies may appear under **`debug/`** on the SD when unmounted cleanly).

Edit **`network.conf`** on the mounted FAT volume if the Pi is not `192.168.1.50/24` with gateway `192.168.1.1`.
