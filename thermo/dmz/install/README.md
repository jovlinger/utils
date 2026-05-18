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
| `../dmz.conf` | **Source** for tweakable settings; `build-and-write.sh` generates the rows below. |
| `network.conf` | Generated one line: `ADDR/CIDR GATEWAY` (editable on the card before boot). |
| `dns.conf` | Generated: one resolver IPv4 per line → host + chroot `resolv.conf`. |
| `dmz-app.env` | Generated: `PORT`, `UI_PORT`, `OAUTH_SESSION_LIFETIME_SECS`, optional public URLs, `LONG_POLL_*`, `LOG_LEVEL`, `OBSOLETE_LOG_SUPPRESS_REPEAT` → chroot `/etc/dmz/dmz-app.env`. |
| `sshd-on-boot` | Generated: `yes` or `no` - pubkey-only sshd on the DMZ network at boot. |
| `buildinfo.txt` | Written at image build time (build id + git). |
| `dmz-boot.start` | Source for apkovl `/etc/local.d/` (also embedded in `dmz.apkovl.tar.gz` on the card). |
| `sshd.sh` | Sources repo script copied to **`/root/sshd.sh`**: LAB **`192.168.88.0/24`** + copies **`install/rescue_authorized_keys`** (card) or **`/root/install/rescue_authorized_keys`** (apkovl) into **`authorized_keys`**, starts **`sshd`**. Requires **non-empty** rescue keys baked at **`build-and-write`** from builder **`~/.ssh/*.pub`**. Not run at boot. |
| `install/rescue_authorized_keys` (on FAT) | **Authoritative** pubkey lines (**not** secrets). Created/overwritten **each image build** from builder **`~/.ssh`**; mirrored to apkovl **`/root/install/`** for identical content when FAT is unplugged or before mount. **`/root/sshd.sh`** installs from FAT first, fallback apkovl. |
| `CARD-README.txt` | Short human notes; copied to `README.txt` on FAT root. |
| [`ROUTERBOARD-DMZ.md`](ROUTERBOARD-DMZ.md) | Home DMZ **design**: Pi outside LAN NAT, separate subnet, port **5000**, DuckDNS **`jovlinger.duckdns.org`**—so topology is not re-argued from scratch. |

Boot diagnostics go to **`/tmp/boot.log`** on the Pi; app output is **`/tmp/dmz_rootfs/var/log/dmz.log`** (chroot tmpfs), with **`/var/log/dmz.log`** on the host as a symlink for convenience (copies may appear under **`debug/`** on the SD when unmounted cleanly).

Edit **`dmz.conf`** on the build host and rebuild, or edit **`install/network.conf`** (and optionally **`dmz-app.env`** / **`sshd-on-boot`**) on the mounted FAT before boot.

On a running Pi, edit **`/etc/dmz/dmz-app.env`** inside the chroot and send **`kill -USR1 <dmz-pid>`** to reload `LOG_LEVEL`, long-poll timeouts, and obsolete-log suppression without rebooting (see `app.py` `reload_dmz_config_from_disk`).
