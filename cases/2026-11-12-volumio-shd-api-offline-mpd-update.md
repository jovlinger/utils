# CASE: SHD Volumio API "offline" while MPD indexes _tags over CIFS

- Date: 2026-11-12
- Hosts / gear: miniDSP SHD (`192.168.88.163`); gmk CIFS `//192.168.88.40/music` with client `nounix`
- Status: remediated (symptoms cleared by restart; root duplicate-_tags index still open on todo:d6d78baa)

## 1. Symptoms

Host pings; Volumio UI / HTTP API on :3000 times out (device looks offline). SPDIF path may still be desired by the user but the app is unusable.

## 2. Evidences

Before remediation (2026-11-12 ~01:41 local):

- ICMP OK; `GET /api/v1/getState` from LAN and from `127.0.0.1:3000` timed out (5-8s, 0 bytes).
- Main Node `/volumio/index.js` state **D (disk sleep)**, RSS ~105 MB (not at V8 heap ceiling ~265 MB).
- TCP: **~230 CLOSE-WAIT**, listen backlog on `:3000` elevated (`LISTEN Recv-Q 315`).
- MPD **Updating DB**, songs **8363** (was 7708 before partial `_tags` walks), MPD RSS **~379 MB** (~38% of 986 MiB RAM), no swap.
- MemFree ~19 MB; `Committed_AS` above `CommitLimit`.
- Journal (~00:46): UI browsed `music-library/NAS/gmk/_tags` then stalled; later queue explode for an album URI never completed in the log window.
- Kernel OOM of an earlier fat MPD (~684 MB) still in dmesg; not a fresh Node heap FATAL in this incident.

Anti-evidence:

- Not "network down": ping and SSH worked.
- Not primarily Node V8 heap OOM this time: Node RSS modest; stuck in **D**, sockets in CLOSE-WAIT.
- Not idle MPD: `updating_db: 1` and song count climbing through `_tags` paths.

After `systemctl restart mpd` then `volumio`:

- `getState` ~18 ms / HTTP 200; CLOSE-WAIT gone; Node state **R**; MPD RSS dropped; `updatedb` false; SPDIF play returned.

## 3. Analysis

A stock MPD database update over this CIFS export walks `_tags` as ordinary directories (`nounix` hides symlinks). That is a **combinatorial indexer job**: each real album tree is visited again under tag aliases, song count and `filename _tags` hits climb, MPD RSS grows, and the single-threaded MPD update blocks other protocol clients. Volumio then stops completing work on `:3000` (CLOSE-WAIT pile-up) while ping still answers.

What is evidenced vs not:

- Evidenced: `updating_db`, songs 7708->8363, `_tags` paths in DB, MPD RSS ~379 MB, API timeouts, ~230 CLOSE-WAIT, Node letter **D** on one `ps` sample, prior dmesg `CIFS VFS: Autodisabling the use of server inode numbers` (MPD `FindAncestorLoop` returns 0 when inode/device are 0, so loop detection does not save you).
- Measured later on the same mount (idle): album `listdir` p50 ~10 ms / max ~49 ms -- not a sleeping disk. A partial `os.walk` of `_tags/album` took ~43 s for ~5000 entries -- volume/algorithm cost, not wire "slowness."
- **Not evidenced (morning CIFS stall):** a `/proc/<node>/stack` capture during that D sample. Waiting on MPD over TCP shows interruptible `epoll`/`read` (**S**).

Best mechanism for the morning stall: **bad/quadratic-ish update over reified `_tags`**, with the API blocked behind that work.

### Same host, later (NFS rescan, 13:36)

Monitor aborted on one sample `State: D` (`node_wchan` read `0`) while `mpc rescan` of `NAS/gmk` (NFS v3, hard) was still `updating_db`. The same sample's `getState` then returned HTTP 200 in 3.36s, and only then did the monitor restart MPD and Volumio. `execSync('/bin/sync')` in `system-update` (`mpd/index.js` ~823) is the event-loop blocker on that path; a tight sample of that call showed parent states R and S only (zero D).

Reproduced on the live SHD, same Node, same mount, no rescan: `fs.readFileSync` of one 32MB FLAC stayed in **D for 7.4s**. Of the D samples, `wchan` was `wait_on_page_bit_common` (31264), `rpc_wait_bit_killable` (45), and `0` (29). A missing-path `statSync` on the mount also hit `rpc_wait_bit_killable`. Local `writeFileSync` and `execSync('/bin/sync')` produced zero D. So letter D here is the NFS client (`TASK_KILLABLE` reported as D). `wchan` `0` during D is normal on this kernel and does not mean the wait ended.

Anti-evidence for "the sync child is why the Node PID was D": the parent of `/bin/sync` stayed S. Anti-evidence for "D until we killed it": HTTP 200 arrived before the restart.

## 4. Remediation

1. Abort the update (`systemctl restart mpd`, then `volumio` so `MpdClient` reconnects) -- why: only killing the updater unblocks Node's D-state wait and drains the accept queue.
2. Do not run stock `mpc update` into `_tags` on this mount until the done-set indexer (or symlink-visible mount) exists -- why: reified tag trees duplicate paths and re-create the stall.
3. Monitor the metrics below on any future library change; treat rising CLOSE-WAIT + Node `D` held across samples + MPD `updating_db` as the offline signature. One `D` sample whose `wchan` is already `0`, followed by HTTP 200, is a finished NFS wait (`wait_on_page_bit_common`), not a stuck process -- restarting there throws away the in-progress DB. The resume monitor now requires three quick consecutive `D` samples (`ABORT_NODE_D_CONFIRM`) before aborting; a transient prints `NODE_D_TRANSIENT`.
4. gmk `nfsstat -s` / `/proc/net/rpc/nfsd` after the 13:36 abort: `badcalls`/`badfmt`/`badauth`/`badclnt` all 0, no nfsd/kern lines in that window. Client `D` was a normal NFS page wait, not a server error.

### User-started app rescan, 2026-11-12 night

A rescan started from the app hours earlier left the SHD pingable (rtt under 1 ms) while `GET :3000/api/v1/getState` and TCP `:6600` returned no bytes, and a new SSH session connected then timed out during banner exchange. An already-open SSH master accepted no further commands (`mpc status` never returned). Same failure as a stock MPD library walk monopolizing the box. The rescan could not be stopped remotely from this host.

## Discussion

Metrics script left on device as `/tmp/shd-js-metrics.py`. Album browse can still look healthy from memory cache while artists/MPD-backed calls hang -- always sample an uncached browse and Node state letter together.
