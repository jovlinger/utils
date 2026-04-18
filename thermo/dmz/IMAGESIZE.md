# DMZ image size notes

Rough **on-disk** estimates for the DMZ HTTP service (same external behavior: HTTP API, JSON validation, Ed25519 zone auth, Google OAuth, in-memory state, access log). **Build toolchains are not included** where noted.

## Parity assumption: OAuth over HTTPS via `curl`

For apples-to-apples comparison, assume **outbound OAuth traffic to Google** (token exchange, optional discovery/userinfo) uses **`curl`** instead of an in-process TLS HTTP stack (`requests` / Authlib client paths).

- **Add** `curl` on Alpine (~0.6–1 MB) when sizing either Python or a minimal Forth stack.
- **Python prod image** should omit test-only packages (`pytest`) and ideally split **server** vs **CLI** deps so `requests` is not required for `app.py` (only `manage.py` today). Replacing Authlib’s HTTP usage with `curl` allows dropping **`authlib`** if you reimplement the small OAuth glue.

Ed25519 verification still runs **in-process** (no `curl` per zone request).

---

## 1. Python (interpreter + requirements + app)

| Component | Approximate disk |
|-----------|------------------|
| Alpine base (musl, busybox) | ~5 MB |
| CPython 3.11 + stdlib | ~45–55 MB |
| openssl, libffi, tini, su-exec | ~4–5 MB |
| `curl` (OAuth parity) | ~0.6–1 MB |
| **site-packages (prod-shaped):** `flask`, `pydantic<2`, `cryptography` (+ cffi/pycparser) | ~30–38 MB |
| App code (`app.py`, `zone_auth.py`, scripts) | &lt;1 MB |

**Total (prod-shaped, OAuth via `curl`, no pytest / no server `requests`): ~75–95 MB on disk.**

Dominant costs: **CPython stdlib** and **`cryptography`** (large native module for Ed25519 and friends). Dropping `authlib` / `requests` / `pytest` saves **single-digit to low tens of MB**, not an order of magnitude.

Reference: [Dockerfile](Dockerfile), [requirements.txt](requirements.txt), [app.py](app.py), [zone_auth.py](zone_auth.py).

---

## 2. Statically linked Go binary (build system not shipped)

| Piece | Approximate disk |
|-------|------------------|
| Single binary (`GOARCH=arm` `GOARM=6`, `CGO_ENABLED=0`, `-ldflags "-s -w"`) | **~11–14 MB** |

Stdlib covers HTTP, JSON, Ed25519 (`crypto/ed25519`), SHA-256. Add `golang.org/x/oauth2` and a small session helper; still one artifact.

Optional: Alpine + tini + binary → **~16–20 MB** if you keep a shell-based entrypoint.

---

## 3. Smaller Forth runtime + Forth app

| Piece | Approximate disk |
|-------|------------------|
| Minimal Forth + POSIX sockets + app source | ~0.5–1.5 MB |
| Static libsodium (or similar) for Ed25519 | ~0.3 MB |
| `curl` (OAuth parity) | ~0.6–1 MB |
| Alpine base (if used) | ~5 MB |

**Forth-only stack (no full OS counted):** ~**0.6–2 MB** plus `curl` for OAuth.

**Typical SD card layout (Alpine + Forth + curl):** ~**6–8 MB** for the app layer on top of a minimal rootfs.

OAuth remains the forcing function: either **`curl`** or embed TLS (e.g. mbedTLS), which grows the footprint.

---

## 4. MicroPython + libsodium (not CPython / not `cffi`)

MicroPython is a **different runtime**: no Flask, no Pydantic, no `cryptography`, and **no `cffi`** (that is a **CPython** C extension; MicroPython does not load it). Same external HTTP behavior implies a **rewrite**: e.g. a small routing layer (`microdot` or hand-rolled `socket` + HTTP/1.1), JSON with `ujson` or built-in `json` where available, and **validation** in plain Python or thin checks.

**Ed25519 verify via libsodium** on MicroPython means a **native C user module** (or vendor patch) that calls `crypto_sign_verify_detached` (or equivalent), linked against **libsodium** statically or as `libsodium.so`—the same crypto surface as “thin CPython + libsodium,” but wired through MicroPython’s **module API**, not `cffi`.

| Piece | Approximate disk |
|-------|------------------|
| `micropython` binary (Unix port, stripped, usable socket/ssl subset) | ~0.5–1.5 MB |
| libsodium (linked into firmware or `.so`) | ~0.2–0.4 MB |
| Frozen / on-disk `.mpy` app (HTTP, routes, JSON glue) | ~0.05–0.3 MB |
| `curl` (OAuth parity) | ~0.6–1 MB |
| Alpine (or similar) if not bare init | ~5 MB |

**Typical “small rootfs + MicroPython + libsodium + `curl`”:** ~**6–10 MB** app layer—same order of magnitude as Forth + `curl`, well below CPython.

**Firmware-style** (interpreter + sodium + app frozen, no Alpine counted): **~1–3 MB** total is plausible on a dedicated port, at the cost of port maintenance and no stock Flask stack.

**Tradeoffs:** you own HTTP correctness, OAuth state, and parity with today’s routes; testing and CI differ from CPython; ARMv6 / soft-float may need a **custom build** of the Unix port or a board-specific firmware.

---

## Summary table

| Stack | Typical on-disk total | Notes |
|-------|------------------------|--------|
| Python + prod deps + `curl` | ~75–95 MB | stdlib + `cryptography` dominate |
| Go static binary | ~11–14 MB | No interpreter |
| Forth + crypto + `curl` (+ Alpine) | ~6–8 MB | Custom surface; OAuth via `curl` |
| MicroPython + libsodium + `curl` (+ Alpine) | ~6–10 MB | **No `cffi`**—native module to libsodium; rewrite from Flask |

---

## Smaller crypto than `cryptography` (Ed25519 verify only)

The DMZ only needs **Ed25519 signature verification** and **SHA-256** (already `hashlib`). It does not need X.509, TLS, or broad cipher suites if the public key is a **raw 32-byte** key.

| Approach | Tradeoff |
|----------|----------|
| **Thin `cffi` / `ctypes` to libsodium** (`crypto_sign_verify_detached`) — **CPython only** | Small native surface; you own ABI and message format. |
| **MicroPython native module → libsodium** | Same crypto as above; **not `cffi`**—implemented in C against MicroPython’s module API. |
| **PyNaCl** | Focused libsodium binding; often less sprawling than PyCA for one primitive. |
| **`pycryptodome` / `pycryptodomex`** | Modular; verify API matches your wire format. |
| **Pure-Python Ed25519** | Smallest install; **higher risk of subtle bugs** and often **non–constant-time** code paths. |

**Why people avoid tiny or pure-Python crypto**

- **Correctness** matters more than raw size; small implementations get less review.
- **Timing / side channels**: critical for **signing** (secret key). For **verify-only** (public key on DMZ), timing is usually **lower severity** than signing, but weak implementations still matter in strict threat models.
- **Performance**: pure Python may be acceptable at low QPS on constrained hardware.
- **Supply chain**: obscure one-file PyPI crypto is often riskier than PyCA / libsodium / PyNaCl.

**Practical takeaway:** For “smaller than `cryptography`” without going pure-Python, **libsodium** verifying the **same** signed payload as today is the usual sweet spot: **PyNaCl or `cffi`/ctypes on CPython**; **native C module on MicroPython** (see §4).

---

## Is there a “stdlib stripper” for CPython?

**Not in a supported, fine-grained “delete half of `Lib/` and keep stock CPython” sense.** The standard library is part of the interpreter build; distributors do not ship a knob per module.

**Related options**

| Tool / idea | Role |
|-------------|------|
| **PyInstaller / cx_Freeze** | Ship app + traced imports; trims **unused third-party** code, not a half-sized CPython install. |
| **Nuitka** | Compiled binary; can drop **unused** modules more aggressively; different build and platform story. |
| **MicroPython** | Smaller footprint; **not** CPython + Flask as-is; see **§4**. |
| **`python3-minimal` (distro packages)** | Fewer **packaging** dependencies, not a curated mini-stdlib. |
| **Manual stdlib deletion** | **Fragile**; easy to break on upgrade or dynamic imports. |

**Practical takeaway:** Shrink **venv / Docker layers** (split requirements, no test tools on device, smaller crypto binding if acceptable). For a **much** smaller runtime, change **language or runtime** (Go, Forth, MicroPython), not “strip CPython stdlib” in production.
