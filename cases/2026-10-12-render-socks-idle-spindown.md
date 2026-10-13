# CASE: Render free tier SIGTERM during SOCKS use

- Date: 2026-10-12
- Hosts / gear: Render free web service `tailscale-exit` (`render_socks5`), Tailscale Serve ports 1080 and 1055
- Status: open

## 1. Symptoms

`redget queue work --socks5-hostname 100.73.69.32:1080` timed out. The Render log then shows `boot: Sending SIGTERM to tailscaled` and `tailscaled exited`.

## 2. Evidences

The last magicsock line is `2026/10/13 02:06:56` with `usec=716607646`. SIGTERM is `2026/10/13 02:10:06`. `usec` is microseconds since `tailscaled` start, so that process began near `01:54:59` and was signaled about 15 minutes and 6 seconds later.

The retry command is `2026/10/12T22:09:10` local (EDT, UTC-4), which is `02:09:10` UTC. SIGTERM is 56 seconds after that.

Anti-evidence: this is not a 3-minute idle timer. The 3 minutes between the last magicsock line and SIGTERM are the remainder of the 15-minute window. Tailnet contact was already happening and did not move the deadline. Render's own health checks were configured (`/healthz`) and the instance still died on that 15-minute mark, so those checks do not reset it either.

## 3. Analysis

A Render free web service is stopped after 15 minutes without an inbound request on its public URL. `containerboot` logs `Sending SIGTERM to tailscaled` while that stop is in progress. The `boot:` prefix is that shutdown, not a crash inside `tailscaled`.

SOCKS on port 1080 and the HTTP proxy on port 1055 arrive through Tailscale Serve, on the userspace netstack. Those bytes never pass Render's public HTTP edge, so a client that is mid-download does not count as traffic. The idle clock keeps the time it had at boot, or at the last public HTTP request, and the platform kills the container under the client.

## 4. Remediation

`render/render_proxy.py` GETs `$RENDER_EXTERNAL_URL/healthz` when a proxy socket is accepted, and again every 4 minutes while a proxy connection stays open. That request has to leave the container and come back through Render's edge. A request to localhost does not, which is why the existing health server never kept the instance up.

The running image does not contain this until the commit is pushed and `render_socks5_util up --deploy` builds it. After that, a live transfer should log `keepalive: https://.../healthz` and should not get SIGTERM at the 15-minute mark from boot.

## Discussion

A short SOCKS connection still arms one ping after it closes, so a burst of API calls resets the window even when no socket stays open for the whole ping. Idle time with no proxy sockets still sleeps, which is what keeps the free-tier hours from running all month.

If a later deploy logs `keepalive:` and SIGTERM still arrives 15 minutes after boot, Render is not counting the hairpin request. The next change is a ping from outside the service, not a shorter interval.
