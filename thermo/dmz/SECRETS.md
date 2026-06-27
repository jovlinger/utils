# `thermo/priv/` - local-only material

Everything under `thermo/priv/` is **gitignored** except `README.md` and is **per dev/build host**. Only private material lives there; public/non-secret counterparts live under `thermo/config/`.

| Subdir | Purpose | Generator | Consumer |
|--------|---------|-----------|----------|
| `priv/zone/priv.pem` | Ed25519 private key used by twoway -> DMZ signing | `make -C thermo/dmz zone-keys` | Onboard bind-mounts it into the twoway container |
| `config/zone/pub.pem` | Matching Ed25519 public key | `make -C thermo/dmz zone-keys` | **`build-and-write.sh` always bakes** it into `install/zone-pub.pem` |
| `priv/oauth/` | Google OAuth client secret, Flask `SECRET_KEY`, and privacy-sensitive allowed account regex | Create in Google Cloud Console and locally | **`build-and-write.sh` always bakes** these private files |
| `config/oauth/google-client-id` | OAuth client ID string | Google Cloud Console | **`build-and-write.sh` always bakes** it |
| `priv/ssh-host/` | Stable rescue **`sshd`** host private keys for the Pi 1B | `install/gen-dmz-rescue-host-keys.sh` | apkovl `/etc/ssh/` (baked into the SD image) |
| `config/ssh-host/` | Matching public host keys | `install/gen-dmz-rescue-host-keys.sh` | Known-hosts verification and apkovl public key files |

**Treat `thermo/priv/` like private material.** Back it up if you care about stable Pi identities; never commit it; copy between dev hosts only over a trusted channel.

## Quick reference

Generate (or regenerate) the zone keypair:

```bash
make -C thermo/dmz zone-keys                  # writes thermo/priv/zone/{priv,pub}.pem
```

This writes `thermo/priv/zone/{priv,pub}.pem`.

Prepare `thermo/config/zone/pub.pem` (after `zone-keys`), `thermo/config/oauth/google-client-id`, and `thermo/priv/oauth/` (three required one-line private files; see table below), then:

```bash
cd thermo/dmz
./build-and-write.sh                         # build dist/dmz.img (fails fast if anything is missing)
./build-and-write.sh /Volumes/PIBOOT       # build + flash when the card is passed
```

`build-and-write.sh` reads public config from `thermo/config/` and private material only from `thermo/priv/`; there are no path overrides.

Distribute the **private** half to the onboard Pi at `thermo/priv/zone/priv.pem` (mode `0400`), then deploy the onboard stack - see [`../KEYS-AND-CERTS.md`](../KEYS-AND-CERTS.md) section 1 for the full ops procedure.

## OAuth files

Create `thermo/config/oauth/google-client-id` and `thermo/priv/oauth/` with **these filenames**, each file **one line** (no JSON, no quotes):

| File | Content |
|------|---------|
| `config/oauth/google-client-id` | OAuth 2.0 Web client ID string |
| `priv/oauth/google-client-secret` | OAuth 2.0 client secret |
| `priv/oauth/flask-secret-key` | Long random secret for Flask session signing (same value across reboots for stable cookies) |
| `priv/oauth/allowed-email` | **One line:** Python regex for `re.fullmatch` on the Google account email (case-insensitive). Example: `^jovlinger@gmail\\.com$` or `^jovlinger@(gmail|googlemail)\\.com$`. Required for SD images - `build-and-write.sh` refuses to build without it. Loaded as `ALLOWED_EMAIL_PATTERN` in [`start.sh`](start.sh). For Docker without this file, you may set `-e ALLOWED_EMAIL_PATTERN=...` or legacy `-e ALLOWED_EMAIL=one@address`. |

**Authorized redirect URIs** in Google Cloud must include every URL your users hit for the callback, e.g. `http://jovlinger.duckdns.org:5000/authorize` if the router forwards external **5000** to Flask `PORT`, plus any LAN or HTTPS URL you use later. After `/authorize`, Flask **`302`**s once to the HTML UI: **`THERMO_UI_PUBLIC_ORIGIN`** if set, else **scheme + hostname** stored in the session when **`GET /login`** ran, else from the callback request — never **`/ui/context`** in **`Location`**.

Build and flash:

```bash
cd thermo/dmz
./build-and-write.sh /Volumes/PIBOOT
```

To enable OAuth **without** rebaking the image, copy the same client files onto the SD card under `install/` (FAT partition); `google-client-id`, `google-client-secret`, and `flask-secret-key` must appear together or `dmz-boot.start` skips OAuth; copy `allowed-email` too if you use the regex allowlist.

Docker / dev: pass `-e GOOGLE_CLIENT_ID=… -e GOOGLE_CLIENT_SECRET=… -e SECRET_KEY=…` instead of files (see [`../consumed/dmz-CLOUD.md`](../consumed/dmz-CLOUD.md)).
