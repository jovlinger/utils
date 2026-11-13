# Bookmark -- SHD NanoPi revive + don't-walk MPD deploy; BLOCKED on no network to SHD and BOOT not on this host (2026-11-13)

created: 2026-11-13T19:32:20Z
created-by: cursor-agent on gmk (wrong machine for /Volumes/BOOT)

Handoff to a FRESH session on blackair (has /Volumes/BOOT). Read this first.
Zero chat history assumed.

Revive miniDSP SHD Volumio (NanoPi NEO3, wired-only, was 192.168.88.163 /
minidsp-shd.local). Goal: inspect microSD BOOT (and rootfs if mountable),
fix obvious breakage or flash a restore image; then install the don't-walk
MPD binary so the app never runs stock walk again.

## Where we are

- Don't-walk Walk.cxx / Walk.hxx committed and pushed (see Repos below).
- Armhf stripped binary ready on gmk: `/tmp/mpd-dontwalk` (BuildID
  sha1 `3bace544bd5f7209fa5e14bf1dcb84b5fb9b83cf`, ~1.7MB, MPD 0.23.5
  feature-poor: alsa+flac+zlib+cue+database only). Deploy helper:
  `/tmp/deploy-mpd-dontwalk.sh` (exited STILL_DOWN earlier).
- Python prototype + fixture test on utils branch (see Repos).
- SHD: powered but no ARP/ping at `.163` after reboot; external/SPDIF play
  does not prove Ethernet. Agent on gmk cannot see `/Volumes/BOOT`.
- Stock SHD `/usr/bin/mpd` was still 0.23.15 before the wedge; patched binary
  was never installed. Partial DB last seen ~10189 songs / 2563 `_tags` hits
  after RSS abort. Operator rule: test AND deploy on pass; overwrite
  `/usr/bin/mpd`, and `mpdorig`/`mpdsacd` if present; rollback to
  `/usr/bin/mpd.stock-0.23.15` if service dies.
- Todo: `todo:d6d78baa` (branch `d6d78baa-mpd-indexer-real-paths`), store
  dottodo. Cases:
  `utils/cases/2026-11-12-volumio-shd-api-offline-mpd-update.md`,
  `utils/cases/2026-11-11-volumio-shd-stale-updatedb.md`.

## The blocker [class: env/infra | awaiting-human]

SHD Ethernet does not answer ARP at 192.168.88.163; gmk has no mount of the
microSD. BOOT is on blackair at `/Volumes/BOOT`. Ruled out: "slow MPD
self-scan will self-heal" (scan needs an address; earlier stock rescan still
answered ping). Slow fsck only plausible for a few minutes after hard reboot;
hours later it is not that.

## How it blocks the goal

Cannot SSH/deploy MPD or remount NFS until the board has L3 again; cannot
inspect card from gmk. NOT blocked: inspect `/Volumes/BOOT` on blackair,
fsck/mount the ext4 root partition if present, locate restore image, pull
repos below, scp `/tmp/mpd-dontwalk` from gmk once network or card write is
available.

## Next steps

0. Re-verify blocker: `ls /Volumes/BOOT` and
   `ping -c1 192.168.88.163` (or current DHCP lease from MikroTik
   192.168.88.1).
1. Inspect BOOT: `uEnv.txt` / `boot.ini` / `cmdline` / overlays; look for
   corrupt or empty essentials. Volumio usually has FAT boot + ext4 root;
   macOS often mounts only BOOT -- also attach the Linux root partition
   (ext4) via a Linux VM or Linux host if network config / mpd live there.
2. If breakage obvious (empty/corrupt boot files, failed fsck on root), fix
   in place. Else find restore: miniDSP/Volumio SHD image (OEM), not a
   generic FriendlyARM NanoPi image (would drop Dirac/Volumio OEM). Prefer
   any local img under Downloads or prior backups before downloading.
3. When SHD is reachable again: install `/tmp/mpd-dontwalk` over
   `/usr/bin/mpd` and `mpdorig`/`mpdsacd` if present; check `/etc/mpd.conf`
   for plugins the slim build lacks; restart mpd; rollback to
   `mpd.stock-0.23.15` if inactive. Do NOT start stock `mpc rescan` /
   `mpc update` of NAS/gmk.
4. Known gap before treating binary as final "one walk": C++ still
   `IsAliasDirName` deletes `_tags`/`_meta` by name and done-set hits
   `DeleteNameIn`; groomed AC wants directory entries kept without second
   song rows (`todo:d6d78baa` body / objid:0007).

## Repos committed and pushed this handoff

| Repo | Branch | Tip | Role |
|------|--------|-----|------|
| https://github.com/jovlinger/MPD | `d6d78baa-dontwalk` | `sha:eb0f927` | Fork of MusicPlayerDaemon/MPD 0.23.5; Walk.cxx/hxx don't-walk |
| https://github.com/jovlinger/utils | `d6d78baa-mpd-indexer-real-paths` | `sha:0c1d6e1` | `efficient_scan.py`, `test_indexer_counts.py`, this `BOOKMARK.md` |
| https://github.com/jovlinger/utils | `master` | `sha:c26116d` | SHD CASE files under `cases/` |

Local nested checkout (not vendored into utils):  
`/home/johan/github.com/jovlinger/dottodo/worktrees/github.com/jovlinger/utils/d6d78baa-mpd-indexer-real-paths/third_party/MPD`  
tracks `jovlinger` remote `d6d78baa-dontwalk`.

Pull on blackair:

```bash
git clone -b d6d78baa-dontwalk git@github.com:jovlinger/MPD.git
git clone -b d6d78baa-mpd-indexer-real-paths git@github.com:jovlinger/utils.git utils-d6d78
# cases also on utils master @ c26116d
```

Binary still only on gmk until copied:  
`scp gmk:/tmp/mpd-dontwalk ~/tmp/` (from blackair once gmk SSH works that way).

## Costed knowledge (do NOT re-derive)

- SHD: NanoPi NEO3, Volumio 3.912, wired-only, no Wi-Fi management path.
  Debug UART 1500000 8N1 on NEO3 header if chassis allows.
- Last known IP 192.168.88.163; gmk LAN `enx6c1ff7197a0b` = 192.168.88.40;
  gateway MikroTik 192.168.88.1. After wedge: ARP INCOMPLETE/FAILED, "No
  route to host" on :22 and :3000; `minidsp-shd.local` often unresolved.
- SSH as `volumiooem` (not stock volumio); sudo password via `sudo -S` is
  `minidspshd` (secret by reference: prior `/tmp/up.txt` on gmk was SHD
  user/pass lines). ControlMaster path used while up:
  `/tmp/shd-volumiooem@192.168.88.163:22`.
- NFS: `192.168.88.40:/mnt/sdb2/music/flac` -> `/mnt/NAS/gmk`,
  `ro,vers=3,hard,nolock`. Music root `/mnt/NAS/gmk/files`. On-disk
  `files/.mpdignore` still lists `_tags`/`_meta`; empty bind-mount over
  `.mpdignore` does not survive reboot.
- Node State D during index = NFS page/RPC wait in the Node thread
  (`wait_on_page_bit_common` / `rpc_wait_bit_killable`), not a Volumio
  "updatedb" flag. `execSync('/bin/sync')` parent stays S. Monitor must
  confirm D x3 (0.25s gaps) before abort; second rescan aborted on
  `mpd_rss_mb>=400` instead.
- App Update == `mpc update`; `mpc rescan` stronger. Python
  `efficient_scan.py` does not talk to MPD. Fixture test: stock logical
  104 vs don't-walk 4 on 4 unique files.
- Built mpd is 0.23.5 not 0.23.15; slim meson flags may reject volumio
  mpd.conf plugins -- deploy script rolls back if `systemctl is-active mpd`
  fails.
- Dead ends: waiting for ping self-heal; stock rescan of NAS/gmk; leaving
  stock as `/usr/bin/mpd` while Volumio can copy `mpdorig`/`mpdsacd` back;
  gmk agent reading `/Volumes/BOOT`; SSH from gmk to balasar/blackair with
  current keys (Permission denied publickey).

## Operating notes

- Resume machine: **blackair** (`blackair.local` / `BlackAir.local`,
  192.168.88.59), not gmk. Card path: `/Volumes/BOOT`.
- Todo CLI from utils git root: `todo` / `todo.py`; store is dottodo, not
  `utils/.todo`. Active todo `d6d78baa`.
- Operator: "There is ZERO utility on a local fix." Deploy on pass.
- Do not delete microSD contents without explicit confirmation.
- gmk sudo often `sudo -A` askpass; screen `sudo-stick` was for sticky tty
  sudo on gmk only.

## Last instruction

As soon as you have read this BOOKMARK file and have confirmed the environment
is ready to continue work, **DELETE** this file (and optional EVIDENCE.md if
fully absorbed). Update the `state:` line in `TODOs.md` to include
`resumed <date>` when present.
