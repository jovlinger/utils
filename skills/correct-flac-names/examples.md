# Examples: correct FLAC names

Store root used below: `/mnt/sdb2/music/flac/files/`. Musicology:
`../bin/musicology` (utils sibling).

## Sidecar priority (authoritative)

Walk in order; first non-empty artist/album wins:

| Order | Path | Notes |
|------:|------|-------|
| 1 | `.meta.combined.json` | Prefer; schema 2: `meta.artist` / `meta.album` |
| 2 | `.meta.johan.json` | Local curated; `metadata.*` else `local.*_guess` |
| 3 | `.meta.<online>.json` | musicbrainz, discogs, lastfm, … |
| 4 | `.meta.txt.json`, then `.meta.cue.json` | Last among sidecars |

Also present (supporting, not outranking a filled higher tier):

| Path | Role |
|------|------|
| `SPECS/*.cue` | Raw cue; track `FILE` basenames |
| `SPECS/*iNFO*.txt`, `SPECS/*.txt` | Secondary hints only |
| Track symlinks / `*.flac` / `*.dsf` | Current filenames |

Skip `_tags/` and `data/` when surveying.

---

## Colon in album dirname (P0)

**Before:** `VA - Verve Remixed: The First Ladies 2013`

Illegal `:` for Samba/VFAT **and** leftover `VA -`. Sidecar artist
`Various Artists` / `VA` is not the folder artist.

**After (dir):** `Verve Remixed - The First Ladies`  
(year `2013` → year tag; `:` → `-` already implied by dropping the subtitle colon)

```text
DIR  VA - Verve Remixed: The First Ladies 2013
  ->  Verve Remixed - The First Ladies
```

Apply from `files/` with **`shadup mv`** (not bare `mv`):

```bash
SHADIR=/mnt/sdb2/music/flac
DB=$HOME/Music/shasrv/shadup.db
cd "$SHADIR/files"
shadup -v --shadir "$SHADIR" --db "$DB" mv --dry-run \
  "VA - Verve Remixed: The First Ladies 2013" \
  "Verve Remixed - The First Ladies"
shadup --shadir "$SHADIR" --db "$DB" mv \
  "VA - Verve Remixed: The First Ladies 2013" \
  "Verve Remixed - The First Ladies"
```

Tags: `various;curated` + `artist;ververemixed`. Tracks may still be
scene-style — optional follow-up (`shadup mv` per file).

---

## Usenet / scene dotted rip name (pop-rock)

**Before:** `Roxy.Music.Avalon.1982.UIGY-9672.SHM-SACD.DSD`

Usenet/scene naming: dots for spaces, catalog + format tokens glued on.
VFAT-safe already, but **incorrect** vs pop/rock convention.

Sidecar walk:

| Tier | Source | Artist | Album |
|------|--------|--------|-------|
| 1 | `.meta.combined.json` `meta` | Roxy Music | Avalon |
| 2+ | (not needed) | — | — |

`meta_sources` may show provenance (`cue` / agree); still treat **combined** as
the winner. Drop rip noise (`UIGY-9672`, `SHM-SACD`, `DSD`); year optional.

**After (dir):** `Roxy Music - Avalon` (or `Roxy Music - Avalon (1982)`)

```text
DIR  Roxy.Music.Avalon.1982.UIGY-9672.SHM-SACD.DSD
  ->  Roxy Music - Avalon
```

```bash
SHADIR=/mnt/sdb2/music/flac
DB=$HOME/Music/shasrv/shadup.db
cd "$SHADIR/files"
shadup --shadir "$SHADIR" --db "$DB" mv \
  "Roxy.Music.Avalon.1982.UIGY-9672.SHM-SACD.DSD" "Roxy Music - Avalon"
```

Same pattern for siblings:
`Roxy.Music.Siren.1975.…`, `Roxy.Music.Country.Life.1974.…`, etc.

Only if combined were empty would you fall through to johan → online →
`.meta.txt.json` / `.meta.cue.json` (those last two also say Roxy Music / Avalon
here).

---

## `The` / `, The` artist forms (provider discovery)

Same method: `/tmp` copy, dereference flacs,
`musicscan --provider musicbrainz --provider discogs --provider lastfm --force`.

**Pixies — Doolittle** (canonical: Pixies):

| Dirname | MB | Discogs | Last.fm |
|---------|----|---------|---------|
| `Pixies - Doolittle` | ✓ → Pixies | ✓ → Pixies | ✓ → Pixies |
| `The Pixies - Doolittle` | ✓ → Pixies | ✗ | ✓ → Pixies |
| `Pixies, The - Doolittle` | ✓ → Pixies | ✗ | ✓ → Pixies |

**The Pogues — Rum Sodomy & the Lash** (canonical: The Pogues):

| Dirname | MB | Discogs | Last.fm |
|---------|----|---------|---------|
| `Pogues - Rum Sodomy & the Lash` | ✓ → The Pogues | ✓ → The Pogues | ✓ → The Pogues |
| `The Pogues - Rum Sodomy & the Lash` | ✓ → The Pogues | ✓ → The Pogues | ✓ → The Pogues |
| `Pogues, The - Rum Sodomy & the Lash` | ✓ → The Pogues | ✓ → The Pogues | ✓ → The Pogues |

Forms are **not** always equivalent for *lookup* without retries
(Pixies/Discogs). **Dirname policy:** always strip leading `The` / trailing
`, The` from the artist segment. Catalog spelling (may include `The`) stays in
`.meta.*.json`. `musicscan` retries with/without `The`.

| Artist (catalog) | Homogeneous dirname |
|------------------|---------------------|
| Pixies | `Pixies - Doolittle` |
| The Pogues | `Pogues - Rum Sodomy & the Lash` |

No `VA -` on main-artist albums **or** on compilations. Compilations use the
movie / DJ / series as the dirname artist. Details in `SKILL.md`.

---

## Denoise dirname titles (not The-strip alone)

Year and encoding do **not** stay in the folder name; year → tag.

| Wrong (partial fix) | Right |
|---------------------|-------|
| `Psychedelic Furs - Forever Now (flac, 1982)` | `Psychedelic Furs - Forever Now` |
| `Album Leaf - [1999] An Orchestrated Rise To Fall [Flac]` | `Album Leaf - An Orchestrated Rise To Fall` |
| `Doors - 2013 - Infinite [2013 US Analogue Productions … SACD]` | `Doors - Infinite` |

Multi-disc pair — same album string, one disc-marker style:

| Wrong | Right |
|-------|-------|
| `Beatles - The Beatles - 1967-1970 (CD1)` / `… (The Blue Album), Disc 2 of 2` | `Beatles - The Beatles 1967-1970 (The Blue Album) CD1` / `… CD2` |

## Collisions → `DUP`

If the target exists, append ` DUP` (again if needed): `Album`, `Album DUP`,
`Album DUP DUP`. Never overwrite.

## Rename provenance (shadup DB)

Prior album directory names are recorded by **`shadup mv`** in `stored_files`:
old path rows get `end=now()`, new rows get `start=now()`. Do not write
`original-album-name` into `.meta.johan.json` — that sidecar field is obsolete.

---

## No `VA -` (compilations use movie / DJ / series)

Do **not** leave `VA -` or `Various Artists -` on any album dir. Kind is a
tag (`various;soundtrack` / `various;curated` / `various;collection`).

| Leftover | Target | Tags |
|----------|--------|------|
| `VA - Pulp Fiction- Music From the Motion Picture` | `Pulp Fiction - Music From the Motion Picture` | `various;soundtrack` `artist;pulpfiction` |
| `VA - DJ-Kicks- DJ Cam` | `DJ Cam - DJ-Kicks` | `various;curated` `artist;djcam` |
| `VA - Verve Remixed- The First Ladies` | `Verve Remixed - The First Ladies` | `various;curated` `artist;ververemixed` |
| `VA - The Best of The Pogues` | `Pogues - The Best of The Pogues` | not various — single-artist anthology |

Main artist + guests → still `Artist - Album` (Pixies, Pogues). Movie titles
keep leading `The`; band dirnames strip it.

Helper: `tag_classify.va_rename_target`.

---

## Series already sanitized in-tree

Existing pattern to match:

- `DJ Cam - DJ-Kicks`
- `Erlend Øye - DJ-Kicks- Erlend Øye`
- `Hotel Costes - Hotel Costes 5`
- `Cafe Del Mar - Volume 15 Quince`

MusicBrainz may still say `DJ-Kicks: Kid Loco` or `Various Artists`. Prefer
the hyphenated series form already used on disk; do not reintroduce `:` or
`VA -`.

---

## Year-prefix / scene mislabels (musicology will not fix)

`parse_album_dirname` splits on the first ` - `; a leading year becomes the
**artist**. Scene names without ` - ` yield `(None, None, …)`. Sidecars may be
wrong or empty; the basename stays. This skill must notice, collate, and
propose `shadup mv` renames.

| On disk | parse artist | Target (illustrative) |
|---------|--------------|------------------------|
| `1996 - Verve Jazzclub - Herbie Mann - Verve Jazz Masters 56` | `1996` | `Herbie Mann - Verve Jazz Masters 56` |
| `2005 - Café Del Mar - 25th Anniversary 1980-2005 [3CD]` | `2005` | `Cafe Del Mar - 25th Anniversary` |
| `10-tony martinez … porque soy rumbero flac` | `(none)` | `Tony Martinez … - Porque Soy Rumbero` (from cue/meta) |

Do **not** keep `YYYY - …` as a browsing form. Year → tag.

## Cue-driven collection

Album: `1973 - Verve Jazzclub - Verve Records Jazz Box [10LP]`

Use sidecar priority first; raw cue is for track `FILE` / multi-performer layout
when higher tiers lack tracks. Kind = `various;curated` (Verve Jazzclub).
**Drop** the leading year from the dirname (year → tag); dirname artist is
the series, not `VA` and not `1996`: `Verve Jazzclub - Verve Records Jazz Box`.

---

## Classical subtitle

**Before (meta):** `Puccini: Greatest Hits`  
**In-tree form:** `Giacomo Puccini - Puccini- Greatest Hits`

Sanitize `:` → `-`; keep composer-forward dirname convention.

---

## SPECS rip (generic)

Same class as Avalon: dotted scene dirname. Prefer `.meta.combined.json` when
present; else walk johan → online → txt/cue. Example shape:
`Miles.Davis.Kind.Of.Blue.2001.HYBRiD.2.0.CS-64935.SACD.DSD` →
`Miles Davis - Kind of Blue` (edition token only if needed to disambiguate).

---

## Tag mirror note

`_tags/album/DJ-Kicks: DJ Cam` can still contain `:` even when the real album
dir uses `-`. Fixing album dirs does not by itself rewrite tag strings; after
album dir renames (`shadup mv`) run `shadup refresh-extracted-tags` (and
`postingest --force_retag` if combined `artist;*` still says `variousartists`).
Prefer `;`-namespaced tags (`artist;ververemixed`, `various;curated`) with
slugged values and no `:` in values (related: groom-musicology-tags).
