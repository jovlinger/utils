# Install (SD card contents)

Files here are copied to **`install/`** on the boot FAT by `build-and-write.sh`.

## Stable rescue SSH host keys (not in git)

Pi rescue (**`sh /root/sshd.sh`**) installs **`install/rescue_authorized_keys`** into **`/root/.ssh`** then starts **`sshd`**. Stable **SSH host keys** across flashes:
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
| `sshd.sh` | Sources repo script copied to **`/root/sshd.sh`**: LAB **`192.168.88.0/24`** + copies **`install/rescue_authorized_keys`** (card) or **`/root/install/rescue_authorized_keys`** (apkovl) into **`authorized_keys`**, starts **`sshd`**. Requires **non-empty** rescue keys baked at **`build-and-write`** from builder **`~/.ssh/*.pub`**. Not run at boot. |
| `install/rescue_authorized_keys` (on FAT) | **Authoritative** pubkey lines (**not** secrets). Created/overwritten **each image build** from builder **`~/.ssh`**; mirrored to apkovl **`/root/install/`** for identical content when FAT is unplugged or before mount. **`/root/sshd.sh`** installs from FAT first, fallback apkovl. |
| `CARD-README.txt` | Short human notes; copied to `README.txt` on FAT root. |
| [`ROUTERBOARD-DMZ.md`](ROUTERBOARD-DMZ.md) | Home DMZ **design**: Pi outside LAN NAT, separate subnet, port **5000**, DuckDNS **`jovlinger.duckdns.org`**—so topology is not re-argued from scratch. |

Boot diagnostics go to **`/tmp/boot.log`** on the Pi; app output is **`/tmp/dmz_rootfs/var/log/dmz.log`** (chroot tmpfs), with **`/var/log/dmz.log`** on the host as a symlink for convenience (copies may appear under **`debug/`** on the SD when unmounted cleanly).

Edit **`network.conf`** on the mounted FAT volume if the Pi is not `192.168.1.50/24` with gateway `192.168.1.1`.
