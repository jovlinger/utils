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
| [2026-10-27-spinme-reactivity-dies.md](2026-10-27-spinme-reactivity-dies.md) | Glass clock/scroll die: URD gated on backlight + Core B blocked in poll/albumart |
| [2026-10-29-readynas-smart-vs-frontview.md](2026-10-29-readynas-smart-vs-frontview.md) | ReadyNAS Frontview hides SMART; smartctl reads both hdc/hde |
| [2026-11-01-spinme-taskactor-1to1-stacks.md](2026-11-01-spinme-taskactor-1to1-stacks.md) | Watch: TaskActor 1:1 FreeRTOS stacks may exhaust SRAM; hybrid n:m later |
| [2026-11-11-volumio-shd-stale-updatedb.md](2026-11-11-volumio-shd-stale-updatedb.md) | SHD library UI spin: Node MpdClient disconnected from MPD |
| [2026-11-12-volumio-shd-api-offline-mpd-update.md](2026-11-12-volumio-shd-api-offline-mpd-update.md) | SHD API timeout: Node D-state + CLOSE-WAIT during MPD _tags update |

Copy [TEMPLATE.md](TEMPLATE.md) for a new file. Name: `YYYY-MM-DD-short-slug.md`.
