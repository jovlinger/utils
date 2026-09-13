# Research: Volumio SHD library OOM (2026-09-13)

Ticket: `e09c565e`  
BE tree audited: `/home/johan/github.com/volumio/volumio3-backend`  
Device: miniDSP SHD Volumio 3.912 (`minidspshd`), Node 14.21.3, heap ≈ 253 MiB usable

## Answers (visited-set / SQLite)

### Will a simple visited-set help?

**Two different layers:**

| Layer | Who walks? | Visited-set? |
|-------|------------|--------------|
| Filesystem → MPD DB | **MPD** (`follow_inside_symlinks "yes"` in `mpd.conf.tmpl`) | **Yes, if we owned the walker.** Stock MPD has no “dir inode once” option we can flip from Volumio JS. Symlink cycles / album↔tag DAGs inflate **song count** (SHD saw ~83k paths vs ~7.4k unique inodes). |
| MPD DB → UI | **Volumio** `listAlbums` / stats / `listallinfo` | **No.** These do not walk the FS. They pull MPD command results into **one Node string + arrays**. A visited-set in JS does not shrink `search album ""`. |

So: break shadup cycles (and/or `.mpdignore`) to shrink MPD’s table — necessary hygiene.  
**Product OOM** is still Volumio materializing full-library MPD replies in heap. Visited-set fantasy belongs in an indexer we control (scrap SQLite proved DAG walk is enough; no bloom/filter needed at ~7k dirs).

### Do we need fancy structure (inverse bloom, etc.)?

**No for this library size.** Global `set[(dev,ino)]` of directories is fine (scrap: 6018 dirs, milliseconds). Revisit only if we index millions of nodes.

### SQLite?

| Where | Available? |
|-------|------------|
| SHD OS | **Yes** — `sqlite3` + `libsqlite3-0` |
| `volumio3-backend` `package.json` | **No** — no `sqlite3` / `better-sqlite3`. In-memory: `cache-manager` with **`ttl: 0`** |

Leverage path: add a Node binding **or** maintain `/data/library.sqlite` via CLI/`sqlite3` subprocess; prefer a real binding if we ship a sidecar. Not “already a dependency.”

## Hot paths (evidence)

```js
// mpd/index.js:4
var memoryCache = cacheManager.caching({store: 'memory', max: 100, ttl: 0});
```

**Startup (~5s after MPD ready):** `listAlbums()` + `getMyCollectionStats()`.

**On every `system-database`:** delete `cacheAlbumList`, then `listAlbums()` + `getMyCollectionStats()` again — including mid-scan as MPD emits updates.

**`listAlbums`:** `search album ""` → entire payload in `msg` → `msg.split('\n')` → push album objects → `memoryCache.set('cacheAlbumList', response)` with **ttl 0**.

**`getMyCollectionStats`:** `count group artist` (parse every triple of lines) + `list album group albumartist` (count Album: lines). Full grouped dumps into strings.

**`getTracklist`:** `listallinfo` with **no URI** — full library metadata into one string, then parse to `tracks[]`.

**`listallFolder`:** `listallinfo` scoped to a URI — still can be huge under `_tags/`.

**MPD conf:** `follow_inside_symlinks "yes"`, `follow_outside_symlinks "yes"`.

## Scrap SQLite (gmk) — order of magnitude

Already in ticket Body: DAG-safe audio index **~2.5–3.6 MiB** for ~7.4k unique audio inodes; naive follow exploded past 100 MiB RAM-side growth.

## Recommended plan (implementation order)

1. **Hygiene (utils/shadup):** remove `_meta/<album>/<tag_path> → _tags/...` backlinks; refresh `files/`; confirm no cycles (`find -L` must terminate; scrap DAG cycle_skips near 0 for NOTAGS loops).
2. **BE minimum (overlay on SHD):** on `system-database` / while `updating_db`, **defer** `listAlbums` + `getMyCollectionStats`; rebuild **once** when update finishes; give `cacheAlbumList` a real TTL or explicit invalidate-only-on-idle.
3. **Never** call unbound `listallinfo` / `search album ""` for stats UX; paginate or query aggregates.
4. **SQLite sidecar (next increment):** inode-keyed tracks under `/data`; browse/stats from SQL; MPD remains playback/scanner. Add Node sqlite binding or controlled CLI — measure heap on SHD with `_tags` still mounted.
5. **Deploy:** fork branch → `git` on `/volumio` overlay; `autoUpdate` off; no miniDSP signing. Document OTA shadow footgun.

## Non-goals (this ticket)

- Treating `.mpdignore _tags` as the product fix (lab control only).
- Fancy probabilistic visited structures.
- Replacing Dirac / flashing generic NanoPi images.
