# CASE: SOCKS probe times out while local Tailscale is down

- Date: 2026-10-15
- Hosts / gear: local `tailscale` CLI, Render service `tailscale-exit`, `render_socks5_util up`
- Status: remediated

## 1. Symptoms

`render_socks5_util up` prints `cannot connect to 100.x.x.x:1080 within 5s (timed out)` and exits 1. The Render log shows the container's tailscaled up, then a new instance going live.

## 2. Evidences

`tailscale status --json` has `BackendState`. `Running` means this machine is on the tailnet. `Stopped` means the local daemon is up and the network is down (`tailscale down`). A missing daemon fails the CLI with a connect error instead of JSON.

Anti-evidence: the remote `peerapi: unknown peer 127.0.0.1` lines are connections from inside the container, not from this machine. They do not show whether local Tailscale is up.

## 3. Analysis

The SOCKS port is published only on the tailnet address. Healthz can return that address while this machine has no path to it. Repeating `render_socks5_util up` deploys again and does not bring the local node onto the tailnet.

## 4. Remediation

On that connect failure, `up` runs `tailscale status --json` and prints `BackendState`. `Stopped`, `NeedsLogin`, and any state other than `Running` tell you to run `tailscale up`. `Running` plus a missing or offline peer is reported as that, so a deploy race is not blamed on a down local node.

## Discussion

A new ephemeral node gets a new 100.x address. If local Tailscale is Running and the address is absent from `Peer`, the netmap has not caught up yet. `tailscale status` is the check, not another deploy.
