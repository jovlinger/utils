# DMZ

Internet-facing rendezvous service: interior **zones** and the **controller** exchange state and commands through this Flask app. It keeps no long-lived credentials; it is a scratch-pad for OAuth handoff and zone polling.

## Behaviour

1. **Zones** POST state to an endpoint and receive the latest command for that zone (and timing metadata).
2. **Controller** POSTs commands and receives the latest zone state in reply.
3. The same zone object carries both command and sensor slots.

## Runtime (Docker)

Alpine Linux, **non-root user `dmz` (uid 1000)**. Process chain:

`tini` → **`start.sh`** (root: tmpfs **`/tmp`** only — leaves **`/var/log/dmz.log`** visible for bind mounts; best-effort read-only remount of `/`) → **`su-exec`** → **`run-with-stdout-logged.py`** (stdout/stderr → **`/var/log/dmz.log`**, rotation) → **`run.sh`** → **`pytest`** (non-fatal on failure) → **import probes** → **`python -u app.py`**.

| Path | Role |
|------|------|
| `Dockerfile` | Multi-stage build: Python deps (pydantic **&lt; 2** / pydantic-core from source on musl when needed) |
| `start.sh` | Privileged setup, then drop to `dmz` with log wrapper around `run.sh` |
| `onboard/run-with-stdout-logged.py` (sister repo) | Staged into `.docker-import/` before image build; append child output to a log path with size limits |
| `run.sh` | Always `pytest -q`, then stack probes (log: `/tmp/dmz-run.log`), then `exec` app |
| `app.py` | Flask API |
| `requirements.txt` | Includes `pytest` for tests in the image |

**Port:** `8080` by default (`PORT` env).

```bash
cd thermo/dmz
docker build -t jovlinger/thermo/dmz .
docker run --rm -p 8080:8080 jovlinger/thermo/dmz
```

**`/var/log/dmz.log`** lives on the container writable layer unless you **bind-mount** a host file (as on the Pi). Optional **`--tmpfs /tmp`** avoids using the layer for **`/tmp`**; avoid **`--tmpfs /var/log`** if you need a bind-mounted **`dmz.log`**.

**ENTRYPOINT / CMD:** **`tini`** is the entrypoint; **`/app/start.sh`** is the default **CMD**. A trailing **`docker run … /bin/sh`** replaces CMD, so you get **`tini -- /bin/sh`** (still under **`tini`** for signals).

**Local run:** `make runlocal` — same default entrypoint as production; **http://localhost:8080**, foreground until Ctrl+C; logs go to **`/var/log/dmz.log`** on the container writable layer (use **`docker cp`** or **`docker exec … cat`** while it runs if you need the file on the host).

## Pi 1B: bootable SD image (same root as Docker, `dd` to card)

1. Ensure **`~/.ssh/id_rsa.pub`** exists; it is baked into the apkovl as **`/root/.ssh/authorized_keys`** for rescue SSH after **`sh /root/network-and-sshd.sh`** ( **`192.168.88.200/24`** by default on **`eth0`** ).
2. From **`thermo/dmz`**, run **`./build-and-write.sh`** to build **`dist/dmz.img`** only (no **`sudo`**). To flash in one step, pass the **whole-disk** device: **`./build-and-write.sh /dev/…`** (macOS: **`/dev/rdiskN`**; Linux: **`/dev/sdX`**, not a partition). Then the script prompts for **`sudo`**, runs a **background unmount loop** on that device while the build runs, and **`dd`** when the card is free.
3. Eject the card, insert in Pi 1B, power on.

The image is a **256MB FAT** volume: Alpine Raspberry Pi **3.19.0 armhf** boot files, **`dmz_rootfs.tar`** (docker export of **`linux/arm/v6`**), **`dmz.apkovl.tar.gz`** (haveged + **`install/dmz-boot.start`** as OpenRC `local.d`). Boot logs to **`/tmp/boot.log`** on the Pi RAM root; the app logs to **`/var/log/dmz.log`** (bind-mounted through the chroot). Boot brings up **`eth0`** from **`install/network.conf`**, extracts the tarball, **chroots** into it, runs **`/sbin/tini -- /app/start.sh`** — same chain as the container (including **`run-with-stdout-logged.py`**).

Edit **`install/network.conf`** on the FAT partition before first boot if the defaults are wrong.

Older full pipeline (bwrap, `dmz-init`, etc.) is on branch **`overly_complicated_double_pivot`**.

## Tests

- **Unit / integration (in-process):** `./test/run.sh` or `make test` — see **`test/README.md`**.
- **Smoketests (Docker + HTTP):** **`./smoketest/run.sh`** — see **`smoketest/README.md`**.

## Other paths

- `install/` — files copied onto the SD FAT **`install/`** directory.
- `plan.md` — short architecture summary.
- `planC.md` — fallback: Raspberry Pi OS Lite + on-device `apt`/`git`/`pip` (documented only for now).
