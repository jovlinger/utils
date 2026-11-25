Content-addressed organizer for FLAC (and photos). MusicBrainz and other
providers via musicology sidecars / postingest.

## Playable library entry

`ingest` (PATH: `utils/binlinks/ingest` -> `ingest.sh`) is the **one** command
that enters an album into the playable library. Stages of that path:

1. Hash copy into `data/` + `files/<source-basename>/` (sources removed after verify).
2. If embedded tags on **audio** tracks mostly agree: `shadup mv` to
   `Artist - Album` (+ `CD1` / `DUP` extras). Year is a tag/sidecar, not
   `(year)` in the folder. Never `VA` / `Various Artists` as the folder artist.
3. Then musicology / `postingest` (sidecars -> combined -> importtags -> `_tags`).

Do not run provider scan before step 2 when the dirname is junk. Musicology
does not rename folders and does not rewrite FLAC tags. `postingest`,
`musicscan`, and `shadup mv` alone do not "add" an album to the library.

Repair of albums already in the store: `skills/correct-flac-names` (always
`shadup mv`), then `postingest` / `refresh-extracted-tags` as needed.

## Tag ingest and browse symlinks (step 3)

### Per-directory `_tags` hierarchy (normative)

Every directory under `files/` may carry a `_tags` subdirectory. That tree is
the **root** of the tag hierarchy for that path -- not leftover scrap, and not
derived from the global browse index.

| Kind of directory | Meaning of `files/<path>/_tags` |
|-------------------|--------------------------------|
| Album / audio-bearing leaf (or box that is the album unit) | That album's own tags from musicology / combine / import |
| Non-album parent (discs or nested boxes) | **Union** of its children's `_tags` |

Example: `files/Depeche Mode - 101/_tags` equals the union of
`files/Depeche Mode - 101/disc A/_tags` and `.../disc B/_tags`.

The global browse index `files/_tags/...` is **derived by reading** those
per-directory roots. Musicology writes the roots; refresh (or its successor)
builds the global mirrors from them. Do not treat DB `sha_tags` alone as a
parallel source that ignores on-disk per-directory `_tags`.

The store volume (`/mnt/sdb2` by default) is mounted **read-only**. Anything that
writes under `files/` or `data/` must remount rw (sudo), then remount ro. The
wrappers below do that via `with-ro-remounted-rw`.

| Goal | Command |
|------|---------|
| Full tag path after albums are already under `files/` | `postingest` |
| Rebuild `_meta` / global `files/_tags` from per-directory `_tags` roots (and reconciled DB tags) | `refresh-extracted-tags` |

### `postingest` (import tags into the DB, then rebuild mirrors)

```bash
postingest                  # default: scan files/, combine, importtags, refresh
postingest --skip-refresh   # importtags only; run refresh later
postingest --dry-run
```

Defaults: store `/mnt/sdb2/music/flac`, DB `$HOME/Music/shasrv/shadup.db`
(`POSTINGEST_STORE_ROOT`, `POSTINGEST_DB`). Remounts automatically unless
`POSTINGEST_NO_REMOUNT=1` or already under remount (`SHASRV_RW=1`).

### `refresh-extracted-tags` (symlink mirrors only)

Use when the shadup DB already has tags and you only need to rebuild browse
trees (for example after restoring circular mirrors, or after a wipe of
`files/_meta` / `files/_tags`):

```bash
refresh-extracted-tags      # remount + shadup refresh-extracted-tags + remount ro
refresh-extracted-tags -v
```

Same store/DB defaults as ingest (`SHASRV_STORE_ROOT`, `SHASRV_DB`). Script:
`shadup/refresh-extracted-tags.sh` (binlink after `make -C shadup binlinks`).

Low-level (you remount yourself):

```bash
with-ro-remounted-rw shadup \
  --shadir /mnt/sdb2/music/flac \
  --db "$HOME/Music/shasrv/shadup.db" \
  refresh-extracted-tags
```

### Mirror layout

Refresh rebuilds:

- `_meta/<album>/album` -> real album directory
- `_meta/<album>/<tag_path>` -> `_tags/<tag_path>` (backlink)
- `_tags/<tag_path>/<album>` -> `_meta/<album>`

Cycles between `_meta` and `_tags` are intentional so tag browse and album meta
share one folder. MPD may store symlink path aliases; Volumio browse should use
aggregate MPD list commands so Node does not buffer every path.
