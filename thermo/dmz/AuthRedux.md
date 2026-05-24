DMZ auth Requirements and Plan
==============================

scope: ~/github.com/jovlinger/utils/thermo/dmz
goal: define requirements and plan for dmz (open-to-internet) auth

# this document

This is a live document, to be rewritten by agent during planning and execution phases to track work.
It will not be a permanent fixture, and does not need to be targeted for human consumption.
Keep prose minimal and precise.

# Summary of end state (not current state)

The DMZ host exposes the following ports:

- **jovlinger.duckdns.org:22 sshd**
  Enabled by onboard `/root/sshd.sh`. Done.

<!-- - **jovlinger.duckdns.org:80 → https**
  No TLS termination or HTTP→HTTPS redirect is implemented in the app.
  Would require a reverse proxy (nginx, Caddy, etc.) in front. Not Done. -->

- **jovlinger.duckdns.org:8080** (Docker; `PORT` env; default 5000 in dev `__main__`)
  `app.py` — Flask app. Ed25519 machine auth (`zone_auth.py`) for zone clients
  (twoway, onboard) when `ZONE_PUBLIC_KEY`/`ZONE_PUBLIC_KEY_PATH` is set. Done.
  Google OAuth (Authlib) implemented for human-facing routes (`/zones`,
  `/debug/logs`, `POST /zone/*/command`) when `GOOGLE_CLIENT_ID` is set.
  Restricted to `ALLOWED_EMAIL_PATTERN` (regex from SD `allowed-email` or env) or legacy `ALLOWED_EMAIL`. Done.

- **jovlinger.duckdns.org:8090** (`UI_PORT` in Docker; not port 80)
  `ui_server.py` — ThreadingHTTPServer (not Flask). Proxies `/ui/context`,
  `/ui/command`, and `/ui/diagnostics` to `http://127.0.0.1:${PORT}`.
  These three endpoints are **intentionally unauthenticated** in `app.py`.
  OAuth protection of the UI is Not Done.

# ??? resolved

How does dmz-ui speak to dmz? Answer: already done. `run.sh` starts both
processes together. `ui_server.py` proxies to `localhost:${PORT}`. The three
`/ui/*` routes on `app.py` are open (no auth) by design, with a comment
saying "protect at the edge if needed." The open-UI concern is the remaining
auth gap.

# What is actually missing

1. TLS / port-80 redirect — no reverse proxy in place.
2. OAuth (or equivalent) protection for the three open UI endpoints:
   `GET /ui/context`, `POST /ui/command`, `GET /ui/diagnostics`.

# Approaches to protect the UI endpoints

## A. Add OAuth to `/ui/*` in `app.py` (minimal code change)
Apply `_authorize_global_read`-style session check to `ui_context`,
`ui_command`, and `ui_diagnostics`. Requires the browser to complete the
Google OAuth flow before seeing the UI. Simplest diff; breaks the "protect
at the edge" comment design principle, but is self-contained.

## B. Move OAuth enforcement into `ui_server.py`
The ThreadingHTTPServer already wraps every request. Add a session-cookie
check there and redirect to `app.py`'s `/login` when unauthenticated.
Requires sharing the Flask `SECRET_KEY` for cookie verification (or a
separate cookie store). Keeps `app.py` routes unchanged.

## C. Reverse-proxy with oauth2-proxy in front of `ui_server.py`
Run `oauth2-proxy` (or similar) on port 80/443 in front of port 8090.
It handles Google OIDC and forwards authenticated requests. Zero Python
changes; adds an external process. Clean TLS boundary. Best fit for
production; more infra to manage on the Pi image.

## D. Merge dmz-ui into `app.py`
Eliminate `ui_server.py`; serve the UI bundle from Flask. Gate `/ui/*`
with a `@login_required` decorator backed by the existing OAuth session.
Reduces process count; removes the proxy layer; makes auth uniform.
Larger refactor; loses the current isolation between the two servers.

## E. Network-trust only (no app-level auth on UI)
Leave UI endpoints open; enforce access at the router/firewall so
`8090` is not reachable from the internet (only from LAN or VPN).
Requires no code changes; relies entirely on network policy. Acceptable
if the threat model only concerns remote attackers.
