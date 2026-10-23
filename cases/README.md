# cases

Troubleshooting write-ups for the next agent (and a tired human at 2am).

Each CASE is one incident. Read the CASE skill before writing or applying one:
[`../skills/case/SKILL.md`](../skills/case/SKILL.md).

## Cases

| File | One line |
|------|----------|
| [2026-08-11-gmk-minidsp-cifs.md](2026-08-11-gmk-minidsp-cifs.md) | Volumio/SHD lost gmk Samba; zombie CIFS (last FLACs ~Aug 6–7) |
| [2026-10-12-render-tailscale-kube-client.md](2026-10-12-render-tailscale-kube-client.md) | Render Tailscale containerboot exits looking for a kube service account |
| [2026-10-12-render-socks-idle-spindown.md](2026-10-12-render-socks-idle-spindown.md) | Free-tier SIGTERM 15 minutes after boot while SOCKS is in use |
| [2026-10-15-render-socks-local-tailscale-down.md](2026-10-15-render-socks-local-tailscale-down.md) | SOCKS timeout when local Tailscale is running but down |
| [2026-10-16-spinme-ui-lag-dns.md](2026-10-16-spinme-ui-lag-dns.md) | Knob glass lagged seconds because every Volumio call re-resolved .local |
| [2026-10-22-dmz-oauth-markupsafe-sigsegv.md](2026-10-22-dmz-oauth-markupsafe-sigsegv.md) | DMZ OAuth never starts: markupsafe v7 speedups SIGSEGV on the armv6 Pi |

Copy [TEMPLATE.md](TEMPLATE.md) for a new file. Name: `YYYY-MM-DD-short-slug.md`.
