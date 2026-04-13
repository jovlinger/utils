# Onboard HTTP API

## Flask app (port `PORT`, default 5000)

Import the WSGI/Flask instance as **`app`** from **`app`** after adding `thermo/onboard` to `PYTHONPATH`. Daikin command JSON maps to **`State`** in **`heatpumpirctl`** (`heatpumpirctl.State`, `State.from_json`, `State.to_json`). Static help text is in **`constants.help_msg`** (`constants`).

---

## `GET /<path>`

Catch-all route for paths not matched by the explicit routes below (Flask’s `<path:path>` converter allows slashes in `path`). Returns simple HTML with the path and per-path request counts. Intended as a liveness or smoke check, not a stable API surface.

## `GET /help` · `GET /about`

Return JSON `{"msg": ...}` with the same help string from **`constants.help_msg`**.

## `GET /environment`

Returns JSON with current temperature and humidity (one decimal), plus an ISO timestamp. Uses the HTU21D sensor unless test fake values were injected via `POST /test/inject_readings`.

## `POST /test/inject_readings`

When running in a test environment (`common.is_test_env()`), sets fake temperature and humidity from JSON keys `temp_centigrade` and `humid_percent`. Returns `403` outside test env.

## `GET /daikin`

Returns a JSON array of recent Daikin commands (newest first), each entry with `time` and `command` (the `State` JSON). If the rolling history is empty, the array has one element: the current last-applied state (on cold start: off, AUTO mode/fan, 20°C) with `time` JSON `null`.

## `PUT /daikin` · `POST /daikin`

Accepts JSON with a `command` object (or a top-level command dict), parses it as **`heatpumpirctl.State`**, sends it over IR, records it in the rolling queue, and returns `time`, `command`, and `sent` boolean.

## `GET /logs`

Returns JSON with up to the last 200 lines of the log file at `LOG_PATH` (key `lines`), or empty lines if the path is missing or unreadable. Lines are ordered **newest first** (reverse chronological within the tail window).

## `GET /manage`

Returns JSON diagnostic snapshot (time, pid, log level, fake sensor values, Daikin queue size, selected env vars). Requires header **`X-Manage-Token`** to match **`MANAGE_TOKEN`**.

## `POST /manage`

Runs one management action from a JSON body (`action`, plus action-specific fields): inject log lines, change log level, reset state, or fault-injection paths (`assert`, `raise`, `fatal`). Requires the same **`X-Manage-Token`** as `GET /manage`.

---

## UI server (port `UI_PORT`, default 8080)

Separate process: import **`Handler`**, **`main`** from **`ui_server`** with `thermo/onboard` on `PYTHONPATH`. Serves HTML that proxies to the Flask app on `127.0.0.1:$PORT`.

## `GET /`

Serves the thermostat HTML UI (reads latest state from Flask `GET /daikin`, environment line from `GET /environment`, embedded help from `GET /help` and `GET /about`, log excerpt from `GET /logs`).

## `POST /`

Accepts `application/x-www-form-urlencoded` body: either submits a Daikin update (POSTs JSON to Flask `POST /daikin`) or performs a management action (POSTs JSON to Flask `POST /manage` with token from form or `MANAGE_TOKEN` env). Responds with refreshed HTML and a status message.
