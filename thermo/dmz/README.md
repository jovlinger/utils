# DMZ

Internet-facing rendezvous service: interior **zones** and the **controller** exchange state and commands through this Flask app. It keeps no long-lived credentials; it is a scratch-pad for OAuth handoff and zone polling.

## Behaviour

1. **Zones** POST state to an endpoint and receive the latest command for that zone (and timing metadata).
2. **Controller** POSTs commands and receives the latest zone state in reply.
3. The same zone object carries both command and sensor slots.

## Runtime (Docker)

Alpine Linux, **non-root user `dmz` (uid 1000)**. Process chain:

`tini` → **`start.sh`** (root: tmpfs **`/tmp`** only — leaves **`/var/log/dmz.log`** visible for bind mounts; best-effort read-only remount of `/`) → **`su-exec`** → **`run-with-stdout-logged.py`** (stdout/stderr → **`/var/log/dmz.log`**, rotation) → **`run.sh`** → optional **`pytest`** on **`test/`** when **`DMZ_RUN_STARTUP_PYTEST=1`** (otherwise skipped; log **`/var/log/startup_tests.log`** when enabled in Docker) → **import probes** → **`python -u app.py`**.

| Path | Role |
|------|------|
| `Dockerfile` | Multi-stage build: Python deps (pydantic **&lt; 2** / pydantic-core from source on musl when needed) |
| `start.sh` | Privileged setup, then drop to `dmz` with log wrapper around `run.sh` |
| `bin/run-with-stdout-logged.py` (repo root) | Snapshotted from sister `bin` repo; staged into `.docker-import/` before image build. Refresh: `make -C bin all` |
| `run.sh` | Always `pytest -q test` on `test/`, then stack probes (log: `/tmp/dmz-run.log`), then `exec` app |
| `app.py` | Flask API |
| `requirements.txt` | Runtime deps including **`requests`** (for **`manage.py`**) and **`pytest`** for in-container tests; **`requirements-dev.txt`** includes the same set for host venv (`-r requirements.txt`) |

**Port:** `8080` by default (`PORT` env).

**HTTPS:** For a browser-trusted certificate on the public internet (e.g. DuckDNS + Let’s Encrypt), see [HTTPS-TRUSTED-CERT.md](HTTPS-TRUSTED-CERT.md).

**Zone keys + TLS layout (generate, gitignore, distribute):** see **[`../KEYS-AND-CERTS.md`](../KEYS-AND-CERTS.md)**. Generate Ed25519 keys with **`make -C thermo/dmz zone-keys`** (writes private key under **`thermo/priv/zone/`** and public key under **`thermo/config/zone/`**).

```bash
cd thermo/dmz
docker build -t jovlinger/thermo/dmz .
docker run --rm -p 8080:8080 jovlinger/thermo/dmz
```

**`/var/log/dmz.log`** lives on the container writable layer unless you **bind-mount** a host file (as on the Pi). Optional **`--tmpfs /tmp`** avoids using the layer for **`/tmp`**; avoid **`--tmpfs /var/log`** if you need a bind-mounted **`dmz.log`**.

**ENTRYPOINT / CMD:** **`tini`** is the entrypoint; **`/app/start.sh`** is the default **CMD**. A trailing **`docker run … /bin/sh`** replaces CMD, so you get **`tini -- /bin/sh`** (still under **`tini`** for signals).

**Local run:** `make runlocal` — same default entrypoint as production; **http://localhost:8080**, foreground until Ctrl+C; logs go to **`/var/log/dmz.log`** on the container writable layer (use **`docker cp`** or **`docker exec … cat`** while it runs if you need the file on the host).

## Pi 1B: bootable SD image (same root as Docker, `dd` to card)

1. **Required:** at least one **`~/.ssh/id_ed25519.pub`**, **`id_ecdsa.pub`**, or **`id_rsa.pub`** on the **build machine** - merged into **`install/rescue_authorized_keys`** on the FAT and **`/root/install/`** in the apkovl so **`sh /root/sshd.sh`** can install **`authorized_keys`** and start **`sshd`**. Stable **host keys**: **`thermo/priv/ssh-host/`**.
2. Prepare **`thermo/config/zone/pub.pem`**, **`thermo/config/oauth/google-client-id`**, and private files under **`thermo/priv/oauth/`** (see **[`SECRETS.md`](SECRETS.md)**); **`./build-and-write.sh`** fails fast if required files are missing (paths are fixed; no overrides). From **`thermo/dmz`**, run **`./build-and-write.sh`** to build **`dist/dmz.img`** only (no **`sudo`**). To flash in one step, pass the **whole-disk** device: **`./build-and-write.sh /dev/...`** (macOS: **`/dev/rdiskN`**; Linux: **`/dev/sdX`**, not a partition). Then the script prompts for **`sudo`**, runs a **background unmount loop** on that device while the build runs, and **`dd`** when the card is free. **Write progress:** Linux uses GNU **`dd status=progress`**. On macOS, **`brew install pv`** gives a byte-accurate bar and ETA; without **`pv`**, the script prints a **heartbeat every 20s** so long writes are not silent.
3. Eject the card, insert in Pi 1B, power on.

The image is a **256MB FAT** volume: Alpine Raspberry Pi **3.19.0 armhf** boot files, **`dmz_rootfs.tar`** (docker export of **`linux/arm/v6`**), **`dmz.apkovl.tar.gz`** (haveged + **`install/dmz-boot.start`** as OpenRC `local.d`). Boot logs to **`/tmp/boot.log`** on the Pi RAM root; the app logs to **`/var/log/dmz.log`** (bind-mounted through the chroot). Boot brings up **`eth0`** from **`install/network.conf`**, extracts the tarball, **chroots** into it, runs **`/sbin/tini -- /app/start.sh`** — same chain as the container (including **`run-with-stdout-logged.py`**).

Edit **`dmz.conf`** before **`./build-and-write.sh`** (network, sshd-on-boot, long-poll, log level). You can still tweak **`install/network.conf`** on the FAT before first boot.

**Home router DMZ (Pi not on LAN subnet, public port 5000, DuckDNS `jovlinger.duckdns.org`):** see **[`install/ROUTERBOARD-DMZ.md`](install/ROUTERBOARD-DMZ.md)**.

Older full pipeline (bwrap, `dmz-init`, etc.) is on branch **`overly_complicated_double_pivot`**.

## Tests

- **Unit / integration (in-process):** `./test/run.sh` or `make test-local` — see **`test/README.md`**. **`make test-docker`** runs pytest in the built image; **`make test`** runs both.
- **Smoketests (Docker + HTTP):** **`./smoketest/run.sh`** — see **`smoketest/README.md`**.

## Other paths

- `install/` — files copied onto the SD FAT **`install/`** directory.
- `plan.md` — short architecture summary.
- `planC.md` — fallback: Raspberry Pi OS Lite + on-device `apt`/`git`/`pip` (documented only for now).
