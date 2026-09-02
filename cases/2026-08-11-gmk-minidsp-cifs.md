# CASE: miniDSP SHD / Volumio cannot play gmk Samba (zombie CIFS)

- Date: 2026-08-10 … 2026-08-11
- Hosts / gear: `gmk` (Ubuntu Samba, USB 2.5GbE `enx6c1ff7197a0b` = `192.168.88.40`); miniDSP SHD / Volumio 3.912 (`minidsp-shd.local` = `192.168.88.163`, NanoPi NEO3, wired-only)
- Status: remediated

## 1. Symptoms

- From the SHD, network music off gmk Samba failed (browse / play / “add NAS”).
- Operator expected recent client attempts in Samba access logs and saw none (including after 23:50, and still after an SHD reboot).
- Wired Ethernet was suspected.
- `gmk` had not had an intentional net-config change in a long time; operator treats gmk as wired-only.
- After the SHD itself was rebooted, logs still looked like “no new client,” which felt incompatible with “stale mount” as the whole story.

## 2. Evidences

**For**

- Operator **used the SHD in Volumio capacity well into early August**. That is the streamer (library, radio, Qobuz/Tidal, …), not merely Dirac/analog. It does **not** by itself prove the gmk CIFS mount was healthy: webradio (e.g. WMBR, still on the queue when we looked) and streaming services do not need that mount. It **does** kill “SHD was a brick since Jun 17.”
- Operator recollection (**almost certain**): played **FLACs** (i.e. the library / gmk NAS) until **Aug 6 or 7**. Treat as strong but not logged. That puts last known-good CIFS **after Jul 30**, so the Jul 30 smbd restart did not leave a permanent zombie.
- gmk boots: **Jun 17 09:48** → **Aug 10 23:35** (no Aug 4 reboot). smbd also died **Jul 30 06:21** (restart, no host reboot), **Aug 10 10:35** (`killall -9 smbd`, operator), **Aug 10 23:35** (this boot). Any of those tears down CIFS TCP.
- **Aug 10 23:35** reboot explains the dead mount *we found that night*. It is not the onset if pain predated it. First gmk-side event *after* “early August use” is **Aug 10 10:35** kill `-9`.
- SHD already had a configured CIFS share (Volumio alias `music` → gmk `music`). Before a rescan the MPD library still showed ~99k tracks.
- After `mpc update` / Volumio “update music database,” stats went to **0**. Live log: `lsinfo` / empty `music-library/NAS/music`. The index had been walking a dead or empty mount.
- Volumio mounts CIFS with `guest` or creds plus `ro,...,noauto,soft`. It remounts at Volumio start (`initShares`), not when the *server* comes back.
- From gmk, guest `smbclient` list/read of `//192.168.88.40/music` worked the whole time.
- Wired path SHD↔gmk: ~0.3–0.6 ms, 0% loss, 1 hop, ARP on the dongle. SHD hardware has no Wi‑Fi.
- Samba `logging = file`, no `log level` (default 0). Per-client files `log.minidsp` and `log.192.168.88.163` are **0 bytes**, mtime **2025-10-06**. Empty file ≠ no session.
- After adding a **new** Volumio share `gmk` → `//192.168.88.40/music` (SMB3, guest), SHD opened **ESTABLISHED** `.163 → .40:445` with real bytes. Library rebuilt (~100k). Playback of `NAS/gmk/Aim - Cold Water Music/01. Intro.flac` confirmed by ear.
- After **SHD reboot**, a **new** TCP session appeared (not the pre-reboot 5-tuple). Library still full under `NAS/gmk`. Same silent Samba log files.

**Anti-evidence (wrong theories)**

- Cable / L1 down: contradicted by link 2500 Mb/s full, ping, and later a working CIFS session on that same NIC.
- Samba on gmk broken for everyone: contradicted by local and on-LAN guest list/read; Sonos `.26` also had idle TCP to `:445`.
- Operator changed net config tonight: no. Wi‑Fi profile `Trazan och Banarne` is from **2022-06-28**, `autoconnect=yes`. NetworkManager brought `wlo2` up **by itself** after the 23:35 boot (`192.168.88.64`). That is leftover autoconnect, not a new design.
- “SSH with the password from the net”: stock `volumio`/`volumio` and `root`/`volumio` were **denied**. miniDSP does not publish the SHD password. Port 22 was closed until `/dev` `enableSSH`.
- “After SHD reboot it must still be an old client, therefore Samba is ignoring newcomers”: false. Fresh TCP + full library + audible play. Logs stay empty because **log level is 0**, not because smbd prefers old clients.
- Dual-home / `gmk.local` → `.64` is a discovery footgun. It is not proven as the onset: the box was usable into early August, and Wi‑Fi may have been autoconnected for the whole Jun 17–Aug 10 uptime.
- “Jun 17 reboot left the SHD unusable”: **anti-evidence** — Volumio was in active use into early August. “Aug 4 reboot”: **no such boot**.
- “Volumio use into early August means NAS/CIFS worked”: radio/cloud still would not prove it. **FLAC until ~Aug 6–7** (operator, almost certain) does: mount was alive then. Guest PAM closes **Aug 7 20:17 and 22:41** are consistent with *someone* still hitting Samba that evening (IP not logged).

## 3. Analysis

CIFS is not “a folder on the network.” It is a **TCP session** (usually port 445) that the client keeps open. The SHD’s Linux `mount.cifs` holds that session. If **smbd dies** (host reboot, `systemctl restart`, `kill -9`), the session is gone. The mountpoint can still exist; `ls` / MPD may show **yesterday’s directory cache**, or hang, or look empty. Volumio’s `soft,noauto` share will **not** notice gmk coming back and reconnect. A **client** reboot *does* remount (`initShares` on Volumio start) — which is why an SHD reboot after the new `gmk` share was saved came up healthy.

Onset of the NAS break is in **~Aug 7 … Aug 10 23:35**. Jul 30 is out if the FLAC memory holds. Remaining gmk-side blows: **Aug 10 10:35** `killall -9 smbd`, **Aug 10 23:35** reboot. Nothing in logs names a hit on Aug 8–9; a client-side SHD glitch in that gap is possible but unevidenced.

MPD’s music library is a **second cache**. Huge artist/album counts can be true of the last successful scan, not of the disk you can read *now*. Updating the database against a dead mount **erases** the library (we did this once while probing). That is not data loss on gmk; it is the index catching up with an empty view.

Samba at log level 0 writes almost nothing. It still creates `log.%m` on first historic connect and may never touch it again. **PAM** `session closed for user nobody` is a better “someone talked SMB” signal than those files. `ss` to `:445` from `.163` is better still.

Separately: if a host has a **saved Wi‑Fi profile with autoconnect**, a reboot will dual-home it even if nobody “uses Wi‑Fi.” Avahi and NetBIOS then advertise the same name on two IPs. Clients that look up `gmk.local` may hit `.64`. That is a **discovery** footgun, not the reason an already-mounted CIFS died. Operator intent (“wired only for years”) and NetworkManager behavior can disagree.

miniDSP Volumio is a fork: SSH defaults from volumio.com do not apply. Use the web API / `/dev` live log when you cannot get a shell.

## 4. Remediation

**Why each step:** restore a *new* CIFS session to a *stable* address; stop the box from growing extra identities on the next boot; do not trust hostname browse or empty Samba logs.

1. On gmk, confirm Samba answers on the **wired** address: `smbclient -N -L //192.168.88.40` and guest read of share `music`.
2. In Volumio, add (or edit) the NAS by **IP**, not name: `192.168.88.40`, share `music`, guest, SMB3. A **new alias** (`gmk`) avoids fighting a hung old mountpoint (`/mnt/NAS/music`).
3. Wait for MPD to reindex. Play one known FLAC. That is the pass/fail, not `log.minidsp`.
4. Delete the dead Volumio entry (`music`) so `lsinfo` stops erroring on a missing dir.
5. If gmk must stay wired-only: disconnect Wi‑Fi, `connection.autoconnect no` on the old SSID, `nmcli radio wifi off` (persists). Raise ethernet autoconnect-priority. Confirm `gmk.local` → `.40` only.
6. Optional: raise Samba `log level` if you want the next outage to leave fingerprints. Optional: restart `nmbd` after killing `.64` so NetBIOS does not keep answering the dead IP.

Adaptations (seaweed): NFS dies the same way on server reboot — remount, do not stare at yesterday’s MPD counts. If the SHD must use a hostname, give that name **one** address. If guest auth fails, it will say permission denied in Volumio live log; that is a different case.

## Discussion

The mechanism we proved is still **dead CIFS + stale MPD**, not a bad cable and not Samba ACLs. Last likely-good FLAC play ~**Aug 6–7**. Next dated smbd deaths **Aug 10 10:35** and **23:35**. Aug 10 23:35 is when we observed the corpse. The SHD kept a dead session and a pretty library until we added a new mount.

We almost blamed Wi‑Fi as an intentional config change. It was a 2022 NetworkManager profile waking up on boot. Dual-home mattered for `gmk.local` / `smbtree` / `smbclient -L gmk.local.`; it was a side quest.

We almost treated empty `/var/log/samba/log.minidsp` as “SHD never connected.” After a *client* reboot that was still empty while `ss` showed a live session and a track was playing. Log level 0 is not a witness.

Triggering Volumio `scanDatabase` while the old mount was dead wiped the stale 99k index. Honest, but rude. Do not scan to “see if it works” until `ss` or a file read proves the mount is alive.

Stock Volumio SSH passwords are a dead end on this SHD. `/dev` `enableSSH` opens port 22; login still needs miniDSP’s private password. Live log + `callMethod` `networkfs.addShare` / `listShares` were enough. `listShares` can **hang** on `df` of a stale CIFS mount — do not use that as your only probe.

Leftovers: old alias `music`; possible stale `nmblookup gmk` → `.64` until nmbd forgets; Tailscale still on gmk (fine for this case).
