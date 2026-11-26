# CASE: Volumio SHD library UI spins; Node MpdClient disconnected

- Date: 2026-11-11
- Hosts / gear: miniDSP SHD Volumio 3.912 (`minidsp-shd.local` = `192.168.88.163`); gmk CIFS `//192.168.88.40/music` on `/mnt/NAS/gmk`
- Status: remediated

## 1. Symptoms

UI showed spinning library/index arrows and would not present the album list (browse appeared to stall). `GET /api/v1/getState` had `"updatedb": true` while SPDIF input was playing.

## 2. Evidences

Before restart:

- MPD itself was healthy and idle: no `updating_db`, `list albumartist` / `list album group albumartist` returned in tens of ms over a fresh TCP socket; Songs 7708; `tag_cache` mtime Nov 9.
- `ss` showed **no ESTABLISHED** Node connection to `:6600` (only LISTEN on MPD and TIME-WAIT from ad-hoc probes).
- `GET /api/v1/browse?uri=albums://` returned 1708 items in ~0.07s from **memoryCache** (on-device `listAlbums` already uses `list album group albumartist`).
- `artists://` and `genres://` timed out (>20s / >45s). Those paths call `clientMpd.sendCommand` and do not have a warm cache hit.
- CIFS `/mnt/NAS/gmk` listed promptly (not the Aug 2026 zombie-CIFS case).

Anti-evidence:

- Not a live MPD indexer hang: MPD answered aggregate list commands quickly; song count and tag_cache were frozen, not growing.
- Not "UI wrong about updatedb only": uncached library browses truly stalled in Node because the MPD client socket was dead.
- Albums API success was not proof the UI library worked: cache hid the dead client.

After `systemctl restart volumio`:

- `updatedb` cleared to false; SPDIF resumed.
- `artists://` 1312 items in 0.14s; `albums://` 1708 in 0.42s; `genres://` and `music-library/NAS/gmk` OK.

## 3. Analysis

Volumio's Node process keeps a long-lived MPD client. When that client is disconnected (here: MPD had been kernel-OOM-killed earlier and replaced; Node `index.js` stayed up from Nov 9), commands queued on `clientMpd` never complete. Cached `albums://` can still look fine. Any browse that must talk to MPD spins forever, and the UI keeps the indexing/spinner chrome (`updatedb` may also stick true). MPD being idle is necessary but not sufficient; Node must have a live session on port 6600.

## 4. Remediation

1. Confirm the split: raw MPD (`mpc` / TCP `status`) idle vs Node browses that need MPD hanging; check `ss -tan | grep 6600` for an ESTAB client.
2. Restart `volumio` (not only MPD) so `MpdClient` reconnects -- why: the hang is in Node's dead client, and MPD restart alone left Node stranded once already.
3. Re-check `artists://` (uncached) before trusting `albums://` (often cached).

## Discussion

First pass wrongly stopped at "stale updatedb; MPD idle." That ignored the user's stuck album list. Always probe at least one uncached MPD-backed browse (`artists://` / `genres://`) and the Node-to-6600 socket before closing the incident.
