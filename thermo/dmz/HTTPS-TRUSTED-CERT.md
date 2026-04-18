# Trusted HTTPS for DMZ (Let’s Encrypt + DuckDNS)

Hub doc (Ed25519 zone keys + TLS + gitignore): **[`../KEYS-AND-CERTS.md`](../KEYS-AND-CERTS.md)**.

When DMZ is reachable from the public internet, browsers need a certificate chained to a public CA. **Let’s Encrypt** is the usual free option. This deployment’s public hostname is **`jovlinger.duckdns.org`** (**DuckDNS**); it must resolve to the **public IP** of whatever terminates TLS (your DMZ host, a home router port-forward target, or a VPS reverse proxy).

## 1. Prove the name reaches you

From the internet (not only your LAN), confirm the hostname points at the machine that will complete the ACME challenge and serve HTTPS:

```bash
ping -c 2 jovlinger.duckdns.org
```

Update the DuckDNS control panel if your public IP changed. If you port-forward **:443** (and **:80** for HTTP-01) from the router to the DMZ box, that box must be the one running cert issuance.

## 2. Get a certificate

**HTTP-01 (simplest when port 80 is free on that host during issuance):**

```bash
sudo certbot certonly --standalone -d jovlinger.duckdns.org
```

Stop anything else bound to **:80** for the minute certbot runs, or use **webroot** mode behind nginx/Caddy if you already serve HTTP on 80.

**DNS-01 (useful when inbound :80 is blocked or you want automation without opening 80):** use the **certbot-dns-duckdns** plugin with your DuckDNS token so Let’s Encrypt can see a TXT record at `_acme-challenge.jovlinger.duckdns.org`. Follow the plugin’s README for `credentials.ini` and a `certbot certonly --authenticator dns-duckdns …` command.

## 3. Use the files the ACME client wrote

Certbot (typical paths on Linux):

- **Full chain (serve this to clients):** `/etc/letsencrypt/live/<your-host>/fullchain.pem`
- **Private key:** `/etc/letsencrypt/live/<your-host>/privkey.pem`

Configure your **reverse proxy** (Caddy, nginx, Traefik) or the app server to use **fullchain** + **privkey**. Serving only `cert.pem` without the intermediate chain can cause trust errors in some clients.

## 4. Renewal

Let’s Encrypt certs are short-lived (~90 days). Keep Certbot’s **systemd timer** or **cron** `certbot renew` enabled, then reload the proxy after renew (Certbot `deploy-hook` / `renewal-hooks`).

## 5. DMZ in Docker

Mount **read-only** copies of `fullchain.pem` and `privkey.pem` into the container (or mount `/etc/letsencrypt` read-only if you accept the broader exposure), point your process or sidecar at those paths, and expose **443** on the host. Do not commit keys to git.

For **onboarding only** (same LAN, no public name), consider **Tailscale HTTPS** or a private CA instead of Let’s Encrypt; this document is for a **public hostname** on the internet.
