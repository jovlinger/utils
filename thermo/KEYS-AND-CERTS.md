# Keys and certificates (thermo)

Two layers: **zone machine auth** (Ed25519, twoway ↔ DMZ) and **browser TLS** (HTTPS, public CA). Both are **per DMZ deployment** and must **not** be committed.

---

## 1. Zone machine auth (Ed25519)

Twoway signs requests to the DMZ; the DMZ verifies with the matching public key (`thermo/dmz/zone_auth.py`, mirrored on onboard).

### Turn it on

- **DMZ:** set **`ZONE_PUBLIC_KEY`** (PEM string) or **`ZONE_PUBLIC_KEY_PATH`** (file path inside the container/chroot) to the zone’s **public** key.
- **Onboard / twoway:** set **`ZONE_PRIVATE_KEY`** (PEM) or **`ZONE_PRIVATE_KEY_PATH`**, and **`ZONE_NAME`** consistent with the URL path.

When the public key is configured, unsigned sensor posts and (with OAuth off) unsigned global reads/commands are rejected; see `thermo/dmz/API.md` and `_authorize_global_read` in `app.py`.

### HTML UI: DMZ vs onboard

The same **`thermo/ui/ui_server.py`** can run on **either** host:

| Where | Flask API (`PORT`) | HTML UI (`UI_PORT`) | Notes |
|-------|--------------------|---------------------|--------|
| **DMZ Docker image** | `8080` (see `Dockerfile`) | **`8090` by default** (`run.sh` / `Dockerfile`) | `THERMO_UI_BACKEND=dmz`; proxies `127.0.0.1:$PORT` (`/ui/context`, `/ui/command`). |
| **Onboard compose** | `5000` | **`8080`** + optional `UI_EXTRA_PORTS` | Default onboard UI; set **`THERMO_UI_DISABLE=1`** in `install/.env` to skip starting it and use the DMZ UI only. |

So the DMZ **does** offer the bundled HTML UI, but in the stock image it listens on **8090**, not 8080, so it does not collide with the DMZ Flask port. You can set `UI_PORT=8080` on the DMZ only if you change `PORT` or accept a different layout.

### Onboard `docker-compose`: enable twoway signing

1. On the Pi (or build host), `make -C thermo/dmz zone-keys` (or copy `pub.pem` / `priv.pem` from a secure channel).
2. Place **`priv.pem`** on the onboard host (e.g. `/etc/thermo/zone/priv.pem`, mode `0400`, root or service user).
3. Add a **read-only** bind mount on the **twoway** service (and **connectivity-watchdog** if used) so the path exists in-container, e.g. `- /etc/thermo/zone:/keys:ro`.
4. In **`install/.env`** (or `~/.local.sh`):  
   `ZONE_PRIVATE_KEY_PATH=/keys/priv.pem`  
   and ensure **`ZONE_NAME`** matches the DMZ URL path (`…/zone/<ZONE_NAME>/sensors`).
5. On the **DMZ** host (separate compose / Pi image env): set **`ZONE_PUBLIC_KEY_PATH`** (or inline **`ZONE_PUBLIC_KEY`**) to **`pub.pem`**, same material as generated with `priv.pem`.

Order matters: deploy **pub** on DMZ first if you need a short window where signing is optional; once DMZ requires signatures, twoway must have **priv** or sensor posts will **401**.

### Generate and distribute

**Option A — Makefile (writes under `thermo/dmz/.secrets/zone/`, gitignored):**

```bash
# From repo root, after venv exists:
../../create_pipenv.sh thermo/dmz   # if needed
make -C thermo/dmz zone-keys
```

This writes **`priv.pem`** and **`pub.pem`**. Keep **`priv.pem`** only on the onboard host (or secrets manager). Install **`pub.pem`** on the DMZ host and point **`ZONE_PUBLIC_KEY_PATH`** at it (Docker bind-mount, Pi chroot, etc.).

**Option B — Compose / CI (writes `thermo/test/keys/`, gitignored):**

`thermo/test/dockertest.sh` runs `thermo/test/gen_keys.py`, which defaults to `test/keys/` unless **`THERMO_ZONE_KEYS_DIR`** is set (same script as `make zone-keys` uses).

**Option C — Ephemeral keys in tests:**

`thermo/test/testcases/test_e2e.py` generates a keypair in a temp dir for subprocess e2e. **`thermo/dmz/test/test_app.py`** covers unsigned rejection and signed acceptance for sensors/commands/`GET /zones`.

### Test coverage (auth keys)

| Area | Where |
|------|--------|
| Reject unsigned when `ZONE_PUBLIC_KEY` set | `thermo/dmz/test/test_app.py` — `test_unsigned_request_rejected_when_auth_required`, `test_unsigned_command_rejected_when_auth_required`, `test_unsigned_get_zones_rejected_when_auth_required` |
| Accept valid signatures | `test_signed_post_command_accepted`, `test_signed_get_zones_accepted` |
| End-to-end with twoway + DMZ + onboard | `thermo/test/testcases/test_e2e.py` (compose + local modes); `thermo/test/docker-compose.yml` mounts `keys/pub.pem` / `priv.pem` |
| HTTP smoke behaviour vs production auth | `thermo/dmz/smoketest/test_smoke.py` (module docstring: OAuth vs zone signing) |
| CLI signing / `DMZ_URL` | `thermo/dmz/test/test_manage.py` (URL handling; signing exercised via `manage.py` in ops) |

Onboard **unit** tests do not re-implement signing tests; behaviour is covered on the DMZ and in e2e.

---

## 2. TLS certificates (HTTPS, per DMZ hostname)

Public browsers need a cert chained to a public CA (typically **Let’s Encrypt**). This is **separate** from Ed25519 zone keys.

### Documentation

- **Procedure (DuckDNS, certbot, renewal, Docker mounts):** [`thermo/dmz/HTTPS-TRUSTED-CERT.md`](dmz/HTTPS-TRUSTED-CERT.md)
- **DMZ README** (pointer): [`thermo/dmz/README.md`](dmz/README.md) — HTTPS line
- **HTTP API / OAuth vs machine auth:** [`thermo/dmz/API.md`](dmz/API.md)

### Gitignore and layout

- **DMZ checkout:** `thermo/dmz/.gitignore` already ignores **`.secrets/`**. Use e.g. **`.secrets/zone/`** for Ed25519 (`make zone-keys`) and **`.secrets/tls/`** for copies of `fullchain.pem` / `privkey.pem` (or symlinks) if you do not mount host `/etc/letsencrypt` directly.
- **Let’s Encrypt on the Pi** usually lives under **`/etc/letsencrypt/live/<hostname>/`** — do not copy into git; bind-mount read-only into Docker/chroot as described in `HTTPS-TRUSTED-CERT.md`.

### Makefile for TLS

Cert issuance is **interactive** (standalone certbot on :80, or DNS-01 with DuckDNS token). There is **no** safe fully automated `make tls-cert` in-repo without your DNS/provider credentials. Follow **`HTTPS-TRUSTED-CERT.md`**, then point your reverse proxy or app at the issued files.

After issuance, optional local copies for compose experiments:

```bash
mkdir -p thermo/dmz/.secrets/tls
# Then copy or symlink fullchain.pem and privkey.pem into that directory; keep .secrets/ out of git.
```

---

## 3. OAuth (Google) — optional third credential

Human operators use **`GOOGLE_CLIENT_ID`**, **`GOOGLE_CLIENT_SECRET`**, **`ALLOWED_EMAIL`** when OAuth is enabled; same `app.py` paths as in `API.md`. Treat like TLS secrets: environment or secret files, not committed.

---

## Quick reference

| Asset | Role | Typical location |
|-------|------|------------------|
| `priv.pem` / `pub.pem` | Zone Ed25519 | `make -C thermo/dmz zone-keys` → `.secrets/zone/` |
| LE `fullchain.pem` / `privkey.pem` | HTTPS | `/etc/letsencrypt/...` or `.secrets/tls/` copies |
| OAuth client secret | Browser login to DMZ | env / `.secrets` / host-only file |
