---
name: correct-flac-names
description: >-
  Correct album directory and track filenames under a FLAC store so names are
  accurate and Samba/VFAT-safe (notably sanitizing ':'). Use when renaming
  FLAC albums, fixing illegal path characters, reconciling cue/SPECS/meta
  titles, or when the user mentions correct flac names / vfat / samba naming.
disable-model-invocation: true
---

# Correct FLAC directory names

Propose (then optionally apply) renames for album directories and track files so
they are **correct** and **Samba/VFAT-safe**. P0 is filesystem safety; correctness
is secondary and must never reintroduce illegal characters.

## Paths (this repo layout)

| Role | Location |
|------|----------|
| FLAC album tree | `/mnt/sdb2/music/flac/files/` (override with user path) |
| Content store | sibling `data/` under the same shadup root |
| Musicology tooling | sibling checkout `../bin/musicology` (from utils root) |
| Tag mirrors | `files/_tags/…` — rebuild with `shadup refresh-extracted-tags` after album renames |

Skip `_tags/` and `data/` when surveying albums; only rename real album dirs
under `files/`.

## P0: Samba / VFAT path rules

Every **path segment** (album dir basename, track filename stem, cue `FILE`
basenames) must be safe on VFAT and Samba shares:

| Illegal | Action |
|---------|--------|
| `:` | Replace with `-` (or space-hyphen-space when it separates title parts) |
| `<>"/\\|?*` | Replace with `_` |
| Control chars (`ord < 32`) | Drop or `_` |
| Trailing spaces / `.` | Strip |
| Empty after sanitize | Use `_empty` |

Do **not** put `:` back into names for MusicBrainz-style subtitles
(`DJ-Kicks: Kid Loco` → `DJ-Kicks- Kid Loco` or `DJ-Kicks - Kid Loco`). Prefer
forms already common in the tree (many albums already use `-` for this).

Tag namespaces in shadup/musicology use `;` (not `:`): `artist;name`,
`album;title`. Colon in tags is legacy; see `../bin/musicology/fix_johan_colon_tags.py`.

## Data sources (gather candidates)

For each album directory, read **`.meta.*.json` sidecars in this order** (first
non-empty artist/album/track wins; do not let a lower tier override a higher
one):

1. **`.meta.combined.json`** — preferred. Schema 2 uses `meta.artist` /
   `meta.album` (and `meta_sources` for provenance). If missing or thin, fall
   through. Refresh with `metatool --provider=ALL export-json <album>` when you
   need a fresh merge.
2. **`.meta.johan.json`** — local curated / override.
   - `metadata.artist` / `metadata.album` / `metadata.tracks[].title`
   - else `local.artist_guess` / `local.album_guess` / `local.tracks[].title_guess`
3. **Online providers** — `.meta.musicbrainz.json`, `.meta.discogs.json`,
   `.meta.lastfm.json`, … (any remote provider sidecar). Same
   `metadata.*` / `local.*` fields; when several online files disagree among
   themselves, most-common then least-verbose.
4. **`.meta.txt.json`**, then **`.meta.cue.json`** — last among sidecars
   (parsed SPECS/info and cue). Only use when tiers 1–3 have no usable value.

Also gather (never outrank a filled higher-tier sidecar for the *semantic*
name; useful for track `FILE` basenames and as a last resort):

- **Cue sheets** — `*.cue` / `*.CUE` in the album dir or under `SPECS/`
  (`TITLE` / `PERFORMER` / per-track / `FILE "…"`).
- **SPECS** — rip dumps; prefer the `.cue` inside; `*iNFO*.txt` is secondary.
- **Embedded tags** — mutagen / `metatool set-auto` if sidecars are thin.
- **Current dirname / filenames** — always a candidate; often partially sanitized.

## Conflict resolution

When choosing the semantic name:

1. Walk the **sidecar priority** above; stop at the first tier with a usable
   artist/album (and tracks when renaming files).
2. Within the same tier only: **most common**, else **least verbose**.
3. Prefer any filled sidecar over a noisy dirname (`…[24bit…]`, `-GP-FLAC`,
   Usenet/scene dotted forms like `Roxy.Music.Avalon.1982.UIGY-….SACD.DSD`).
4. Never pick a candidate that fails P0 after sanitize.

## Naming conventions by kind

Detect kind from genres/tags, cue performer layout, or dirname cues
(`VA -`, `Various`, `Verve Jazzclub`, composer-first classical).

### Pop / rock (default)

```
Artist - Album
01. Track Title.flac
```

- One primary artist. Prefer the **bare catalog form** of the name in the
  dirname (e.g. `Pixies - Doolittle`), not `The Pixies - …` or `Pixies, The - …`.
  MusicBrainz and Last.fm usually still match the `The` / `, The` variants and
  return the canonical artist; **Discogs often does not** (see experiment
  below). Meta may still say `X, The`; for on-disk paths prefer what providers
  accept as a search key.
- Rewrite Usenet/scene dotted rip dirs to `Artist - Album` (drop catalog /
  codec tokens). Prefer `.meta.combined.json`, then johan, then online, then
  txt/cue — not the dirname.
- Track: zero-padded number, `.` or ` - ` separator, title, original extension.

#### Experiment: `The` / `, The` vs bare artist (Pixies — Doolittle)

Copied `Pixies - Doolittle` to `/tmp`, dereferenced flacs, ran
`musicscan --provider musicbrainz --provider discogs --provider lastfm --force`
on three dirname variants (same tracks):

| Dirname | musicbrainz | discogs | lastfm |
|---------|:-----------:|:-------:|:------:|
| `Pixies - Doolittle` | match → Pixies | match → Pixies | match → Pixies |
| `The Pixies - Doolittle` | match → Pixies | **no match** | match → Pixies |
| `Pixies, The - Doolittle` | match → Pixies | **no match** | match → Pixies |

**Conclusion:** forms are **not** equal for discovery. Prefer bare `Pixies - …`
(and similarly drop leading `The` / trailing `, The` in dirnames when renaming)
so Discogs keeps working; MB/Last.fm already normalize.

### Collections / VA / series

```
VA - Series - Title
YYYY - Series - Artist - Title
```

Examples already in the tree: `VA - DJ-Kicks- DJ Cam`,
`1996 - Verve Jazzclub - Herbie Mann - Verve Jazz Masters 56`.

- Keep series tokens that aid browsing; drop ripper noise (`-GP-FLAC`,
  `[FLAC]`, bare `flac` suffixes) unless needed to disambiguate editions.

### Classical

```
Composer - Work [Label, Disc N]
Artist - Composer Work
```

Examples: `Giacomo Puccini - Puccini- Greatest Hits`,
`Erich Leinsdorf - … - Puccini- Turandot [BMG, Disc 1]`.

- Prefer composer-forward names; sanitize `Composer: Work` → `Composer- Work`.
- Multi-disc: keep `Disc N` in the album dir (or `CD1/` children if already structured).

## Workflow

Copy and track:

```
Correct FLAC names:
- [ ] Scope albums (paths or find illegal chars)
- [ ] Gather candidates (cue / SPECS / .meta.* / export-json)
- [ ] Resolve conflicts + pick convention
- [ ] VFAT-sanitize every segment
- [ ] Emit rename plan (dir + files); dry-run first
- [ ] Apply renames; refresh _tags if using shadup mirrors
```

### 1. Find offenders

```bash
FILES=/mnt/sdb2/music/flac/files
find "$FILES" -mindepth 1 -maxdepth 1 -name '*:*'
find "$FILES" -mindepth 1 -maxdepth 3 \( -name '*:*' -o -name '*\?*' -o -name '*"*' \) ! -path '*/_tags/*'
```

### 2. Build a rename plan

For each album, output a plan (do not apply until confirmed unless the user
asked to apply):

```text
DIR  <old basename>  ->  <new basename>
FILE <old>           ->  <new>
CUE  update FILE "…" lines if track files rename
```

Keep renames on the same filesystem (`mv` / rename) so shadup content-addressed
blobs under `data/` stay valid; only the symlink tree under `files/` moves.

### 3. Apply carefully

- Prefer dry-run listing first.
- Collision: if target exists, stop and report (do not overwrite).
- After album renames that affect tag mirrors: run shadup
  `refresh-extracted-tags` so `_tags/` no longer points at stale basenames.
- Do not “fix” names by writing illegal characters into `_tags/` either;
  album tag values that become path segments must be sanitized the same way.

### 4. Report

Summarize: albums scanned, illegal names found, renames proposed/applied,
sources that won (e.g. “musicbrainz album + cue tracks”), and any skipped
collisions.

## Related code

- `../bin/musicology/` — `scan.py`, `metatool.py`, `audio.py` (`parse_album_dirname`,
  `parse_track_filename`), providers, sidecars
- `shadup/shadup.py` — `_sanitize_tag_mirror_segment`, `tag_mirror_relpath`,
  `refresh-extracted-tags` (note: `:` in tags is treated as a **namespace**
  separator for mirrors; album *values* still need VFAT sanitize)
- `shadup/importtags.py` — uses `;` as artist/album tag separator for path safety

## Examples

See [examples.md](examples.md).
