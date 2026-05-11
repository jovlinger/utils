# `thermo/dmz/.secrets/` — local-only material

Everything under `thermo/dmz/.secrets/` is **gitignored** (`.gitignore: .secrets/`) and is **per dev/build host**. Two kinds of files live here:

| Subdir | Purpose | Generator | Consumer |
|--------|---------|-----------|----------|
| `.secrets/zone/` | Ed25519 zone machine-auth keypair (`priv.pem`, `pub.pem`) used by twoway → DMZ signing | `make -C thermo/dmz zone-keys` | DMZ (pub) baked into SD via `build-and-write.sh --include-pub-key=.secrets/zone/pub.pem`; onboard (priv) bind-mounted into the twoway container |
| `.secrets/oauth/` | Google OAuth client id/secret + Flask `SECRET_KEY` (human login to DMZ UI / browser routes) | Create in [Google Cloud Console](https://console.cloud.google.com/) → APIs & Services → Credentials → OAuth 2.0 Client ID (Web). Generate a long random `SECRET_KEY` (e.g. `openssl rand -hex 32`). | Bake into SD with `build-and-write.sh --include-oauth-dir=.secrets/oauth …`. On boot, `dmz-boot.start` copies them to chroot `/etc/dmz/`; [`start.sh`](start.sh) exports `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `SECRET_KEY` when all three files exist (explicit env overrides). |
| `.secrets/ssh-host/` | Stable rescue **`sshd`** host keys for the Pi 1B (so `known_hosts` does not churn each flash) | `install/gen-dmz-rescue-host-keys.sh` (auto-invoked by `build-and-write.sh` if missing) | apkovl `/etc/ssh/` (baked into the SD image) |

**Treat `.secrets/` like private material.** Back it up if you care about stable Pi identities; never commit it; copy between dev hosts only over a trusted channel.

## Quick reference

Generate (or regenerate) the zone keypair:

```bash
make -C thermo/dmz zone-keys                  # writes .secrets/zone/{priv,pub}.pem
```

Bake the **public** half into a fresh SD image (see [`build-and-write.sh`](build-and-write.sh) for the full flag list):

```bash
cd thermo/dmz
./build-and-write.sh --include-pub-key=.secrets/zone/pub.pem            # build only
./build-and-write.sh --include-pub-key=.secrets/zone/pub.pem /Volumes/PIBOOT  # + flash
```

Distribute the **private** half to the onboard Pi (mode `0400`, root-owned), then point twoway at it via `ZONE_PRIVATE_KEY_PATH` and bind-mount it into the container — see [`../KEYS-AND-CERTS.md`](../KEYS-AND-CERTS.md) §1 for the full ops procedure.

Without `--include-pub-key`, the SD image boots with **machine auth disabled** and the DMZ accepts unsigned `POST /zone/<z>/sensors` from anywhere on the public internet.

## OAuth files (`.secrets/oauth/`)

Create a directory (convention: `thermo/dmz/.secrets/oauth/`, gitignored with the rest of `.secrets/`) with **exactly these filenames**, each file **one line** (no JSON, no quotes):

| File | Content |
|------|---------|
| `google-client-id` | OAuth 2.0 Web client ID string |
| `google-client-secret` | OAuth 2.0 client secret |
| `flask-secret-key` | Long random secret for Flask session signing (same value across reboots for stable cookies) |
| `allowed-email` | *(optional)* Single allowed Google account email; if omitted, [`app.py`](app.py) default `ALLOWED_EMAIL` applies |

**Authorized redirect URIs** in Google Cloud must include every URL your users hit for the callback, e.g. `http://jovlinger.duckdns.org:5000/authorize` if the router forwards external **5000** to Flask `PORT`, plus any LAN or HTTPS URL you use later.

Bake and flash:

```bash
cd thermo/dmz
./build-and-write.sh --include-pub-key=.secrets/zone/pub.pem \
  --include-oauth-dir=.secrets/oauth /Volumes/PIBOOT
```

To enable OAuth **without** rebaking the image, copy the same three files onto the SD card under `install/` (FAT partition); all three must appear together or `dmz-boot.start` skips them and logs a warning.

Docker / dev: pass `-e GOOGLE_CLIENT_ID=… -e GOOGLE_CLIENT_SECRET=… -e SECRET_KEY=…` instead of files (see [`../consumed/dmz-CLOUD.md`](../consumed/dmz-CLOUD.md)).
