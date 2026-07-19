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
(`VA -` / `Various` only when it is a true multi-artist collection;
`Verve Jazzclub`; composer-first classical). Guest features ≠ VA.

### Pop / rock (default)

```
Artist - Album
01. Track Title.flac
```

- One primary artist. **Homogeneous dirname artist:** never start the artist
  segment with `The`, and never store `Artist, The`. Strip both to the bare
  form (`The Pogues` → `Pogues`, `Pogues, The` → `Pogues`). Album *titles* may
  still start with `The` (`… - The Wall`, `… - The Rest of the Best`).
- Provider canonical names (often with `The`) belong in `.meta.*.json`
  (`metadata.artist`), **not** in the album directory name.
  `musicscan` retries lookups with and without `The`
  (`audio.artist_lookup_variants`) so bare dirnames still match catalogs.
- **Target shapes:** `Pixies - Doolittle`, `Pogues - Rum Sodomy & the Lash`.
  Bare / `The` / `, The` inputs must converge on the stripped form.
- Guest features / collaborators on a main-artist album stay under that artist
  (`Artist - Album`). Do **not** prefix `VA -` (see Collections).
- Rewrite Usenet/scene dotted rip dirs to `Artist - Album` (drop catalog /
  codec tokens). Prefer `.meta.combined.json`, then johan, then online, then
  txt/cue — not the dirname. Then apply `The`-strip + title denoise + VFAT
  sanitize.
- Track: zero-padded number, `.` or ` - ` separator, title, original extension.

#### What does **not** belong in the dirname title

The album directory is `Artist - Album` (optionally `Disc N` for multi-disc).
Everything else is tags, sidecars, or basename noise — **strip it from the
dirname**. Do not preserve encoding, years, labels, or remaster tokens “for
browsing” inside the folder name.

| Drop from dirname | Where it goes instead |
|-------------------|------------------------|
| Encoding / container (`flac`, `Flac`, `FLAC`, `dsf`, `SACD`, `DSD`, …) | implied by files; not in title |
| Release / rip year (`1982`, `(flac, 1982)`, `[1999]`, leading `2013 -`) | **year tag** / sidecar `year` (e.g. musicology / embedded tags) |
| Label, catalog, remaster, bit-depth, “Analogue Productions”, `CAPP …`, `US … SA` | edition metadata in sidecars — not the path |
| Ripper junk (`-GP-FLAC`, `[24bit…]`, bare `(flac)`) | drop |

**Anti-patterns → targets (do not stop at The-strip alone):**

```text
Psychedelic Furs, The - Forever Now (flac, 1982)
  ->  Psychedelic Furs - Forever Now
      # year 1982 → year tag; drop (flac, …)

The Album Leaf - [1999] An Orchestrated Rise To Fall [Flac]
  ->  Album Leaf - An Orchestrated Rise To Fall
      # [1999] → year tag; drop [Flac]

The Doors - 2013 - Infinite [2013 US Analogue Productions CAPP DOORS SA SACD]
  ->  Doors - Infinite
      # 2013 → year tag; drop entire edition bracket
```

Wrong dry-run (The-strip only, noise left in place) is **incorrect** — keep
going until the title is just the album name.

#### Multi-disc sets: one elegant album string

Discs of the **same** release must share one album title spelling; only the
disc marker differs (`CD1` / `CD2`, or `Disc 1 of 2` / `Disc 2 of 2` — pick
**one** convention per set and apply it to every disc). Prefer the canonical
provider album title (Blue Album, etc.); do not leave mismatched punctuation
or duplicate “The Beatles” in the title side.

```text
# wrong — pair does not rhyme
The Beatles - The Beatles - 1967-1970 (CD1)
The Beatles - The Beatles 1967-1970 (The Blue Album), Disc 2 of 2

# right — same album string, consistent disc marker
Beatles - The Beatles 1967-1970 (The Blue Album) CD1
Beatles - The Beatles 1967-1970 (The Blue Album) CD2
```

(Exact disc-suffix style may follow an existing tidy peer in the tree; the
requirement is **consistency within the set**, not inventing a third form.)

#### Experiment: `The` / `, The` vs bare artist (pre-homogeneous)

Same method: `/tmp` copy, dereference flacs,
`musicscan --provider musicbrainz --provider discogs --provider lastfm --force`
on three dirname variants **before** musicscan learned to retry `The`.

**Pixies — Doolittle** (catalog: **Pixies**):

| Dirname | musicbrainz | discogs | lastfm |
|---------|:-----------:|:-------:|:------:|
| `Pixies - Doolittle` | match → Pixies | match → Pixies | match → Pixies |
| `The Pixies - Doolittle` | match → Pixies | **no match** | match → Pixies |
| `Pixies, The - Doolittle` | match → Pixies | **no match** | match → Pixies |

**The Pogues — Rum Sodomy & the Lash** (catalog: **The Pogues**):

| Dirname | musicbrainz | discogs | lastfm |
|---------|:-----------:|:-------:|:------:|
| `Pogues - Rum Sodomy & the Lash` | match → The Pogues | match → The Pogues | match → The Pogues |
| `The Pogues - Rum Sodomy & the Lash` | match → The Pogues | match → The Pogues | match → The Pogues |
| `Pogues, The - Rum Sodomy & the Lash` | match → The Pogues | match → The Pogues | match → The Pogues |

**Policy (now):** dirnames always use the stripped artist (`Pixies`, `Pogues`).
Catalog spelling with `The` stays in sidecars. `musicscan` must try with and
without `The` so Discogs/MB keep matching after the strip.

### Collections / VA / series

```
VA - Series - Title
YYYY - Series - Artist - Title
```

Use **`VA -` only for true collections / compilations** — multi-artist
anthologies where there is no single primary artist (soundtracks with many
acts, label samplers, `DJ-Kicks` curated comps, `Verve Remixed`, etc.).
Examples already in the tree: `VA - DJ-Kicks- DJ Cam`,
`1996 - Verve Jazzclub - Herbie Mann - Verve Jazz Masters 56`.

Do **not** use `VA -` when a main artist brings in guests or collaborators
(features, duets, “with …”). Those stay filed under the main artist:
`Artist - Album` (e.g. Pixies / The Pogues albums — never `VA - Pixies - …`).

Same for **single-artist “best of” / anthology** releases: keep the artist
(stripped), not `VA`. Live example:

| On disk now | Homogeneous target |
|-------------|--------------------|
| `The Pogues - The Rest of the Best` | `Pogues - The Rest of the Best` |
| `VA - The Best of The Pogues` | `Pogues - The Best of The Pogues` |

(MusicBrainz artist is `The Pogues` — store that in sidecars; strip `The` /
misplaced `VA -` from the dirname. Album title may keep leading `The`.)

- Keep series tokens that aid browsing; drop ripper noise (`-GP-FLAC`,
  `[FLAC]`, bare `flac` suffixes), years-in-title, and edition brackets — same
  denoise rules as pop/rock (year → tag).
- Tree convention: short `VA`, not MusicBrainz `Various Artists`, in the
  dirname (still VFAT-sanitize the title).

### Classical

```
Composer - Work [Label, Disc N]
Artist - Composer Work
```

Examples: `Giacomo Puccini - Puccini- Greatest Hits`,
`Erich Leinsdorf - … - Puccini- Turandot [BMG, Disc 1]`.

- Prefer composer-forward names; sanitize `Composer: Work` → `Composer- Work`.
- Multi-disc: keep a **consistent** disc marker in the album dir (or `CD1/`
  children if already structured). Same denoise rules: no encoding/year/label
  brackets in the title (year → tag).
- Classical label/`Disc N` in brackets is allowed only when it is the **disc
  identity** for a box (and consistent across the set) — not remaster marketing
  text.
## Workflow

Copy and track:

```
Correct FLAC names:
- [ ] Scope albums (paths or find illegal chars)
- [ ] Gather candidates (cue / SPECS / .meta.* / export-json)
- [ ] Resolve conflicts + pick convention
- [ ] Denoise title (drop encoding/year/edition brackets; year → tag)
- [ ] Harmonize multi-disc album strings within each set
- [ ] Strip The /, The on artist; VFAT-sanitize every segment
- [ ] Resolve target collisions with DUP / DUP DUP / …
- [ ] Emit rename plan (dir + files); dry-run with `shadup mv --dry-run` first
- [ ] Apply dir renames with `shadup mv`; refresh _tags
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

Apply directory renames with **`shadup mv`**, not bare `mv`. It renames on disk
(same filesystem; blobs under `data/` unchanged) and updates `stored_files` path
history (`end` on old rows, `start` on new). Track symlink renames inside an
album use the same command with file paths.

Paths are **relative to `files/`** (stored path prefix), e.g. album basenames at
the top level or `Album/track.flac` for a single file. Run from the store's
`files/` directory so shadir/DB discovery works, or pass `--shadir` explicitly.

```bash
FILES=/mnt/sdb2/music/flac/files
cd "$FILES"

# Rehearse one album dir rename (prints disk + DB plan, no changes)
shadup mv --dry-run "Old Name" "New Name"

# Apply
shadup mv "Old Name" "New Name"

# Track file inside an album (optional follow-up)
shadup mv "New Name/01-old.flac" "New Name/01. Track Title.flac"
```

Sidecars (`.meta.*.json`, cue sheets) move with the directory on disk; edit cue
`FILE "…"` lines manually when track basenames change. Do not use plain `mv` for
anything indexed in `stored_files` — the DB would drift from disk.

### 3. Apply carefully

- Prefer `shadup mv --dry-run` before each batch (or mirror the plan in a log).
- **Collision:** if the target basename already exists (or another planned
  rename claims it), do **not** overwrite. Append ` DUP` to the target name and
  retry; if still taken, append another ` DUP` (repeat until free):

  ```text
  Artist - Album
  Artist - Album DUP
  Artist - Album DUP DUP
  ```

  Call the chosen name out in the action log. Never clobber an existing album
  dir.
- **Rename provenance:** `shadup mv` end-dates the old `stored_files` rows and
  opens new ones with `start=now()`. Prior album dirnames live in the shadup DB
  — do **not** write `original-album-name` into `.meta.johan.json` (obsolete).
- After album renames that affect tag mirrors: run shadup
  `refresh-extracted-tags` so `_tags/` no longer points at stale basenames.
- Do not “fix” names by writing illegal characters into `_tags/` either;
  album tag values that become path segments must be sanitized the same way.

### 4. Report

Summarize: albums scanned, illegal names found, renames proposed/applied
(including any `DUP` suffixes), sources that won, and any skipped deferrals.

## Related code

- `../bin/musicology/` — `scan.py` (`_lookup_with_artist_variants`),
  `audio.py` (`strip_dirname_artist_the`, `artist_lookup_variants`,
  `parse_album_dirname`, `parse_track_filename`), `metatool.py`, providers,
  sidecars
- `../bin/musicology/fix_johan_colon_tags.py` — legacy `:` in tags
- `shadup/shadup.py` — `mv` (disk rename + `stored_files` start/end history),
  `_sanitize_tag_mirror_segment`, `tag_mirror_relpath`, `refresh-extracted-tags`
  (note: `:` in tags is treated as a **namespace** separator for mirrors; album
  *values* still need VFAT sanitize)
- `shadup/importtags.py` — uses `;` as artist/album tag separator for path safety

## Examples

See [examples.md](examples.md).
