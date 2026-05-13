# `thermo/dmz/.secrets/` — local-only material

Everything under `thermo/dmz/.secrets/` is **gitignored** (`.gitignore: .secrets/`) and is **per dev/build host**. Two kinds of files live here:

| Subdir | Purpose | Generator | Consumer |
|--------|---------|-----------|----------|
| `.secrets/zone/` | Ed25519 zone machine-auth keypair (`priv.pem`, `pub.pem`) used by twoway → DMZ signing | `make -C thermo/dmz zone-keys` | **`build-and-write.sh` always bakes** `pub.pem` from **only** `.secrets/zone/pub.pem` into `install/zone-pub.pem`; onboard (priv) bind-mounted into the twoway container |
| `.secrets/oauth/` | Google OAuth client id/secret + Flask `SECRET_KEY` + allowed Google account (human login to DMZ UI / browser routes) | Create in [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials → OAuth 2.0 Client ID (Web). Generate a long random `SECRET_KEY` (e.g. `openssl rand -hex 32`). | **`build-and-write.sh` always bakes** these files from **only** `.secrets/oauth/`. On boot, `dmz-boot.start` copies them to chroot `/etc/dmz/`; [`start.sh`](start.sh) exports `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SECRET_KEY` (explicit env overrides win). |
| `.secrets/ssh-host/` | Stable rescue **`sshd`** host keys for the Pi 1B (so `known_hosts` does not churn each flash) | `install/gen-dmz-rescue-host-keys.sh` (auto-invoked by `build-and-write.sh` if missing) | apkovl `/etc/ssh/` (baked into the SD image) |

**Treat `.secrets/` like private material.** Back it up if you care about stable Pi identities; never commit it; copy between dev hosts only over a trusted channel.

## Quick reference

Generate (or regenerate) the zone keypair:

```bash
make -C thermo/dmz zone-keys                  # writes .secrets/zone/{priv,pub}.pem
```

Prepare **both** `.secrets/zone/pub.pem` (after `zone-keys`) and `.secrets/oauth/` (four required one-line files; see table below), then:

```bash
cd thermo/dmz
./build-and-write.sh                         # build dist/dmz.img (fails fast if anything is missing)
./build-and-write.sh /Volumes/PIBOOT       # build + flash when the card is passed
```

`build-and-write.sh` reads secrets **only** from `.secrets/` under this directory; there are no path overrides.

Distribute the **private** half to the onboard Pi (mode `0400`, root-owned), then point twoway at it via `ZONE_PRIVATE_KEY_PATH` and bind-mount it into the container — see [`../KEYS-AND-CERTS.md`](../KEYS-AND-CERTS.md) §1 for the full ops procedure.

## OAuth files (`.secrets/oauth/`)

Create a directory (convention: `thermo/dmz/.secrets/oauth/`, gitignored with the rest of `.secrets/`) with **these filenames**, each file **one line** (no JSON, no quotes):

| File | Content |
|------|---------|
| `google-client-id` | OAuth 2.0 Web client ID string |
| `google-client-secret` | OAuth 2.0 client secret |
| `flask-secret-key` | Long random secret for Flask session signing (same value across reboots for stable cookies) |
| `allowed-email` | **One line:** Python regex for `re.fullmatch` on the Google account email (case-insensitive). Example: `^jovlinger@gmail\\.com$` or `^jovlinger@(gmail|googlemail)\\.com$`. Required for SD images — `build-and-write.sh` refuses to build without it. Loaded as `ALLOWED_EMAIL_PATTERN` in [`start.sh`](start.sh). For Docker without this file, you may set `-e ALLOWED_EMAIL_PATTERN=...` or legacy `-e ALLOWED_EMAIL=one@address`. |

**Authorized redirect URIs** in Google Cloud must include every URL your users hit for the callback, e.g. `http://jovlinger.duckdns.org:5000/authorize` if the router forwards external **5000** to Flask `PORT`, plus any LAN or HTTPS URL you use later. After `/authorize`, Flask **`302`**s once to the HTML UI: **`THERMO_UI_PUBLIC_ORIGIN`** if set, else **scheme + hostname** stored in the session when **`GET /login`** ran, else from the callback request — never **`/ui/context`** in **`Location`**.

Build and flash:

```bash
cd thermo/dmz
./build-and-write.sh /Volumes/PIBOOT
```

To enable OAuth **without** rebaking the image, copy the same client files onto the SD card under `install/` (FAT partition); `google-client-id`, `google-client-secret`, and `flask-secret-key` must appear together or `dmz-boot.start` skips OAuth; copy `allowed-email` too if you use the regex allowlist.

Docker / dev: pass `-e GOOGLE_CLIENT_ID=… -e GOOGLE_CLIENT_SECRET=… -e SECRET_KEY=…` instead of files (see [`../consumed/dmz-CLOUD.md`](../consumed/dmz-CLOUD.md)).
