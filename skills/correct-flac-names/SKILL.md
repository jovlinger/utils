---
name: correct-flac-names
description: >-
  Correct album directory and track filenames under a FLAC store so names are
  accurate and Samba/VFAT-safe (notably sanitizing ':'). Catches mislabels
  musicology leaves behind (year-as-artist `1996 - …`, scene junk like
  `10-tony…`); notice, collate, propose `shadup mv` fixes. All renames MUST use
  `shadup mv` (never bare `mv`). Use when renaming FLAC albums, fixing illegal
  path characters, reconciling cue/SPECS/meta titles, or when the user mentions
  correct flac names / vfat / samba naming.
disable-model-invocation: true
---

# Correct FLAC directory names

Propose (then optionally apply) renames for album directories and track files so
they are **correct** and **Samba/VFAT-safe**. P0 is filesystem safety; correctness
is secondary and must never reintroduce illegal characters.

## P0: rename only with `shadup mv`

**Never** use bare `mv` / `os.rename` / `Path.rename` for anything under the
store. Album dirs and track files that live in `stored_files` must be renamed
with **`shadup mv`** so disk and DB stay in sync (`end` on old rows, `start` on
new). Plain `mv` leaves the DB pointing at stale paths.

This store (pass explicitly when discovery fails — there is no `.shadir` marker
next to `files/`):

```bash
export PATH="$PWD/extdeps:$PWD/shadup:$PATH"   # from utils root
SHADIR=/mnt/sdb2/music/flac
DB=$HOME/Music/shasrv/shadup.db
cd "$SHADIR/files"
shadup --shadir "$SHADIR" --db "$DB" mv --dry-run "Old Name" "New Name"
shadup --shadir "$SHADIR" --db "$DB" mv "Old Name" "New Name"
```

If `mv` errors with **matched rows span multiple store roots**, run
`shadup --shadir "$SHADIR" --db "$DB" doctor` first, then retry `shadup mv`.
If `mv` errors with **no active stored path matches**, the album is on disk but
not in `stored_files` — run `shadup … reindex-files "<album>"` (or the parent
`files/` tree), then retry `shadup mv`. Do not fall back to bare `mv`.

## Paths (this repo layout)

| Role | Location |
|------|----------|
| FLAC album tree | `/mnt/sdb2/music/flac/files/` (override with user path) |
| shadup store root | `/mnt/sdb2/music/flac` (`--shadir`) |
| shadup DB | `$HOME/Music/shasrv/shadup.db` (`--db`) |
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

1996 - Verve Jazzclub - Herbie Mann - Verve Jazz Masters 56
  ->  Herbie Mann - Verve Jazz Masters 56
      # leading YYYY is NOT the artist; musicology will treat it as one

2005 - Café Del Mar - 25th Anniversary 1980-2005 [3CD]
  ->  Cafe Del Mar - 25th Anniversary
      # same year-as-artist trap

10-tony martinez and cuba … jazz-porque soy rumbero flac
  ->  Artist - Album   # from cue/meta; scene junk is not a name
```

Wrong dry-run (The-strip only, noise left in place) is **incorrect** — keep
going until the title is just the album name. Year-leading and scene dirs that
still look “scanned” are still wrong — see **Musicology will not rename these
for you**.
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
Artist - Album
```

**Not** a target form: `YYYY - Series - Artist - Title`. Leading release years
in the basename are mislabels (year → tag), even when the rest is a real series
like Verve Jazzclub or Café Del Mar. Live offenders still on disk:

```text
1996 - Verve Jazzclub - Herbie Mann - Verve Jazz Masters 56
  ->  Herbie Mann - Verve Jazz Masters 56
      # or VA - Verve Jazzclub - Herbie Mann - Verve Jazz Masters 56
      # if series browsing is the intent; never keep leading YYYY -

2005 - Café Del Mar - 25th Anniversary 1980-2005 [3CD]
  ->  Cafe Del Mar - 25th Anniversary
      # match tidy peers already in-tree (Cafe Del Mar - 25th Anniversary (3-CD))
```

Use **`VA -` only for true collections / compilations** — multi-artist
anthologies where there is no single primary artist (soundtracks with many
acts, label samplers, `DJ-Kicks` curated comps, `Verve Remixed`, etc.).
Example already in the tree: `VA - DJ-Kicks- DJ Cam`.

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

- Keep series tokens that aid browsing **only when they are not a year prefix**;
  drop ripper noise (`-GP-FLAC`, `[FLAC]`, bare `flac` suffixes), years-in-title,
  and edition brackets — same denoise rules as pop/rock (year → tag).
- Tree convention: short `VA`, not MusicBrainz `Various Artists`, in the
  dirname (still VFAT-sanitize the title).

### Musicology will not rename these for you

`musicscan` guesses artist/album from the dirname via
`parse_album_dirname` (`../bin/musicology/audio.py`): split on the **first**
` - `, left = artist, right = album (+ trailing noise stripped). It does **not**
rewrite the directory name.

That mishandles common mislabels:

| On-disk basename | `parse_album_dirname` → `(artist, album, year)` | What goes wrong |
|------------------|-------------------------------------------------|-----------------|
| `1996 - Verve Jazzclub - Herbie Mann - Verve Jazz Masters 56` | `('1996', 'Verve Jazzclub - Herbie Mann - …', 1996)` | Artist becomes the **year**; providers lookup `1996` |
| `2005 - Café Del Mar - 25th Anniversary 1980-2005 [3CD]` | `('2005', 'Café Del Mar - 25th Anniversary 1980-2005', 2005)` | Same — artist=`2005` |
| `10-tony martinez and cuba … jazz-porque soy rumbero flac` | `(None, None, None)` | No ` - ` split → no artist/album guess; lookups starve |

Sidecars may stay empty, thin, or locked to junk queries; the broken basename
survives. **Your job under this skill:** notice these shapes when surveying
(year-leading `19xx`/`20xx - …`, scene/lowercase dashed junk like `10-tony…`,
edition brackets, encoding suffixes), collate them with sidecar/cue evidence,
and **propose** a rename plan for the user (dry-run `shadup mv`). Do not assume
“musicscan already ran” means the dirname is correct. Do not leave year-as-artist
or scene junk as “good enough.”
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
- [ ] Scope albums (illegal chars + year-prefix / scene-junk mislabels)
- [ ] Notice musicology-mishandled shapes (year-as-artist, unparsable scene names)
- [ ] Gather candidates (cue / SPECS / .meta.* / export-json)
- [ ] Resolve conflicts + pick convention
- [ ] Denoise title (drop encoding/year/edition brackets; year → tag)
- [ ] Harmonize multi-disc album strings within each set
- [ ] Strip The /, The on artist; VFAT-sanitize every segment
- [ ] Resolve target collisions with DUP / DUP DUP / …
- [ ] Emit rename plan (dir + files); dry-run with `shadup mv --dry-run` first
- [ ] Propose plan to user (apply only when asked); **`shadup mv` only**; refresh _tags
```

### 1. Find offenders

```bash
FILES=/mnt/sdb2/music/flac/files
# P0 illegal path chars
find "$FILES" -mindepth 1 -maxdepth 1 -name '*:*'
find "$FILES" -mindepth 1 -maxdepth 3 \( -name '*:*' -o -name '*\?*' -o -name '*"*' \) ! -path '*/_tags/*'
# Year-as-artist / leading-year mislabels (musicology treats YYYY as artist)
find "$FILES" -mindepth 1 -maxdepth 2 -type d \( -name '19[0-9][0-9] - *' -o -name '20[0-9][0-9] - *' \) ! -path '*/_tags/*'
# Scene / ripper junk (no "Artist - Album" shape; often lowercase, dashed, trailing flac)
find "$FILES" -mindepth 1 -maxdepth 1 -type d -name '*flac' ! -name '* - *'
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
the top level or `Album/track.flac` for a single file. Always pass
`--shadir` / `--db` for this store (see P0 block above), or run from a cwd where
`.shadir` discovery works.

```bash
SHADIR=/mnt/sdb2/music/flac
DB=$HOME/Music/shasrv/shadup.db
cd "$SHADIR/files"

# Rehearse one album dir rename (use -v; dry-run lines are verbosity ≥1)
shadup -v --shadir "$SHADIR" --db "$DB" mv --dry-run "Old Name" "New Name"

# Apply
shadup --shadir "$SHADIR" --db "$DB" mv "Old Name" "New Name"

# Track file inside an album (optional follow-up)
shadup --shadir "$SHADIR" --db "$DB" mv \
  "New Name/01-old.flac" "New Name/01. Track Title.flac"
```

Sidecars (`.meta.*.json`, cue sheets) move with the directory on disk; edit cue
`FILE "…"` lines manually when track basenames change. Do not use plain `mv` for
anything indexed in `stored_files` — the DB would drift from disk.

### 3. Apply carefully

- **Usenet / scene dotted dirs** with no usable sidecar artist+album: derive
  `Artist - Album` from the basename (drop year / catalog / SACD / DSD tokens),
  then `shadup mv`. Do not leave dotted forms only because meta is empty.
- **Nested multi-disc containers** (e.g. Woodstock box with `Vol. 01`… children)
  are **in scope**. Denoise/sanitize the parent dirname like any other album
  dir. Do not skip them because musicology also scans leaves + parent — that
  dual treatment is orthogonal (`postingest` / groom-musicology-tags).
- **Filesystem collision:** if the target basename already exists on disk (or
  another planned rename claims it), do **not** overwrite the directory.
  Append ` DUP` to the target name and retry; if still taken, append another
  ` DUP` (repeat until free):

  ```text
  Artist - Album
  Artist - Album DUP
  Artist - Album DUP DUP
  ```

  Call the chosen name out in the action log. Never clobber an existing album
  dir. (`shadup mv` itself refuses when the destination path exists on disk.)
- **DB path occupancy:** when the destination path has an active
  `stored_files` row but no conflicting directory, `shadup mv` **end-dates**
  that occupant and inserts the moved SHA — it does **not** invent a `DUP`
  name for DB-only collisions.
- **Rename provenance:** `shadup mv` end-dates the old `stored_files` rows and
  opens new ones with `start=now()`. Prior album dirnames live in the shadup DB
  — do **not** write `original-album-name` into `.meta.johan.json` (obsolete).
- After album renames that affect tag mirrors: run
  `shadup --shadir "$SHADIR" --db "$DB" refresh-extracted-tags` so `_tags/` no
  longer points at stale basenames.
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
