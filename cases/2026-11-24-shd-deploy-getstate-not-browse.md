# CASE: SHD dont-walk deploy looked fine; Volumio browse still dead

- Date: 2026-11-24
- Hosts / gear: miniDSP SHD (`192.168.88.39`); dont-walk MPD 0.23.5; Volumio Node
- Status: remediated

## 1. Symptoms

After `make deploy-dontwalk-shd`, the device "looked identical" to pre-push: library
browse unusable. Deploy logs still reported success (`getState=200`, `mpc` ok).

## 2. Evidences

- Installed `/usr/bin/mpd` md5 matched `../MPD/mpd_indexer/out/mpd (local, unversioned)`; `mpc ls NAS/gmk/files`
  showed `_tags` and not `_meta`; on-device fixture prove against that binary printed
  `PROOF_OK`.
- Production `tag_cache` mtime was **before** the deploy restart -- so live library
  state was not evidence about the new binary.
- `GET /api/v1/getState` returned 200 quickly while `GET /api/v1/browse?...` timed
  out with 0 bytes. Node was `Ssl` (not stuck in D); MPD answered `mpc` over :6600.
- After `systemctl restart volumio` and waiting for getState, browse of
  `music-library/NAS/gmk/files` and `.../_tags` returned 200 with `_tags` present and
  `_meta` absent.

Anti-evidence:

- Not "new MPD binary broken": local fixture prove on the installed binary passed.
- Not "Docker prove lied about Walk.cxx": nested `NAS/gmk/files` + `_meta` ignore
  still holds on SHD once Volumio can talk to MPD again.
- Not CIFS/NFS offline: `mpc` listing the same paths worked during the browse hang.

## 3. Analysis

Deploy restarts MPD (new binary) but left Volumio's long-lived Node process holding a
dead `MpdClient` socket. getState does not need a healthy MPD list path; browse does.
Checking only getState after install therefore cannot detect the failure mode the user
sees in the UI.

Separately, Node `scanFolder` with `.mpdignore = _meta` only still descended into
`_tags`. done-set stops true cycles but not cross-album `_tags` BFS across the whole
library -- a gap the small docker/Node fixtures never hit.

## 4. Remediation

1. After installing MPD, **restart Volumio** and poll until **browse** of
   `NAS/gmk/files` returns 200 (getState can 200 earlier) -- why: Node must open a
   fresh MPD connection, and getState is not that signal.
2. Gate deploy on browse of `.../_tags` (`_meta` absent) plus an on-device fixture
   `PROOF_OK` of `/usr/bin/mpd` -- why: prove UI path and binary behavior without
   trusting a pre-deploy `tag_cache`.
3. Keep a **make test** protocol grep so deploy cannot regress to getState-only -- why:
   docker never runs Volumio; the script contract is the portable detector.
4. Node: **structural skip** of `_tags` / `_meta` in scanFolder even when ignore lists
   only `_meta` -- why: MPD owns indexing `_tags`; scanFolder must not fan out through
   album-local mirrors.

## Discussion

Cousin failure: any playbook that restarts MPD on the SHD and then only curls getState.
Docker `start-test-container` remains the Walk.cxx recreate/prove path; it does not
replace SHD verify.
