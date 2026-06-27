# DMZ HTTP API

Flask application: import `app` from **`app`** after adding `thermo/dmz` to `PYTHONPATH` (or running with that directory on `sys.path`). Request/response shapes use Pydantic models in the same module; import **`ZoneRequest`**, **`ZoneReply`**, **`Sensors`**, **`ZoneState`** from **`app`**. Zone **`command`** payloads are arbitrary JSON (see `POST /zone/<zonename>/command`).

Machine-auth header names and verification: **`zone_auth`** (`thermo/dmz/zone_auth.py`, same `PYTHONPATH` rule).

---

## `GET /version`

Open JSON build provenance endpoint for deployment checks. On SD images, `build-and-write.sh` writes `install/buildinfo.txt` and `dmz-boot.start` copies it into the chroot as `/etc/dmz/buildinfo.txt`, so this endpoint can report `build_id`, `build_date_utc`, `git_sha`, `git_branch`, `git_dirty`, and `source_sha256`. Local dev runs without buildinfo return `{ "available": false }`.

## `GET /login`

Starts the Google OAuth redirect flow when OAuth credentials are configured. Before redirecting to Google, stores **scheme + hostname** (no port) from this request in the signed session for the post-callback HTML redirect. Returns `400` with a JSON error if OAuth is not configured.

## `GET /authorize`

OAuth callback: exchanges the authorization code, checks the Gmail address against `ALLOWED_EMAIL_PATTERN` (regex `re.fullmatch`, from `install/allowed-email` on SD) or legacy exact `ALLOWED_EMAIL`, sets the session, then **302** to the public HTML UI root (**`THERMO_UI_PUBLIC_ORIGIN`** if set, else session value from **`GET /login`**, else scheme+hostname from this request — never **`/ui/context`** in **`Location`**). Returns **503** if none of those apply. On failure returns `400`/`403` with JSON errors; if OAuth is disabled, redirects to `GET /zones`.

## `GET /logout`

Clears the session and redirects to login (if OAuth is enabled) or to `GET /zones`.

## `POST /zone/<zonename>/sensors`

Accepts JSON sensor readings for the named zone, appends them to in-memory state, and returns that zone’s current command and sensor snapshot. When `ZONE_PUBLIC_KEY` / `ZONE_PUBLIC_KEY_PATH` is set, the request must include valid Ed25519 zone signing headers matching the URL zone name.

## `POST /zone/<zonename>/command`

Accepts the JSON body and passes it through to zone command storage, returning that zone’s snapshot. Aside from auth, the server only checks that the body is well-formed JSON (UTF-8) and that every JSON string (object keys and string values) is 7-bit ASCII; otherwise it returns `400`. With a configured zone public key, either valid machine-signed requests or an authenticated browser session (when Google OAuth is enabled) may be used; otherwise OAuth may be required for human operators.

Raw IR replay uses the same command store. Capable onboards recognize:

```json
{
  "command_type": "raw_ir_sequence",
  "sequence": [4500, -4500, 560, -1600, 560, -520],
  "carrier_hz": 38000
}
```

Positive `sequence` values are marks/pulses in microseconds; negative values are spaces in microseconds. `carrier_hz` is optional and currently expected to be `38000` when present.

## `GET /zones`

Returns a JSON object of all known zones and each zone’s latest command and sensor state. Authorization follows `_authorize_global_read`: machine-signed request, OAuth session, or open access when neither machine auth nor OAuth is enforcing, depending on environment variables.

## `GET /ui/context`

JSON snapshot for the shared thermo UI: **`zones`**, **`environments`**, **`zone_states`**. When Google OAuth is configured, **unauthenticated** browser requests (`Accept` containing `text/html`) are redirected to **`/login`**; **authenticated** browser requests are redirected to the **public HTML UI root** (same rules as the **302** from **`GET /authorize`** after login), not JSON. JSON clients use **`Accept: application/json`** (as **`ui_server`** does); without a session they receive **`401`**.

## `POST /ui/command`

JSON body `{"zone": "<name>", "command": { ... }}` — same validation and storage as **`POST /zone/<zonename>/command`**. Same OAuth rules as **`GET /ui/context`** when Google OAuth is configured.

## `GET /debug/logs`

Returns a JSON object with a bounded in-memory list of recent HTTP access records (method, path, status, timestamp). Uses the same authorization rules as `GET /zones`.

## `POST /test_reset`

Test-only hook to replace in-memory `commands` and/or `sensors` from JSON body keys `commands` and `sensors`. Returns a short JSON string `"ok"`.
