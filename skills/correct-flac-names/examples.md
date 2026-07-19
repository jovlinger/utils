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

Live offender (illegal `:` for Samba/VFAT).

Sidecar walk:

| Tier | Source | Artist | Album |
|------|--------|--------|-------|
| 1 | `.meta.combined.json` | (missing) | — |
| 2 | `.meta.johan.json` `local` | VA | Verve Remixed: The First Ladies |
| 3 | musicbrainz `metadata` | Various Artists | Verve Remixed: The First Ladies |
| 3 | discogs/lastfm `local` | VA | Verve Remixed: The First Ladies |

**Wins at tier 2 (johan):** `VA` / `Verve Remixed: The First Ladies`. Keep year
suffix from dirname; VFAT-sanitize `:` → `-`.

**After (dir):** `VA - Verve Remixed- The First Ladies 2013`

```text
DIR  VA - Verve Remixed: The First Ladies 2013
  ->  VA - Verve Remixed- The First Ladies 2013
```

Apply from `files/` (not bare `mv`):

```bash
cd /mnt/sdb2/music/flac/files
shadup mv --dry-run \
  "VA - Verve Remixed: The First Ladies 2013" \
  "VA - Verve Remixed- The First Ladies 2013"
shadup mv \
  "VA - Verve Remixed: The First Ladies 2013" \
  "VA - Verve Remixed- The First Ladies 2013"
```

Tracks may still be scene-style (`01-ella_fitzgerald-….flac`) — optional
follow-up after dirname P0 (per-track renames also use `shadup mv`).

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
cd /mnt/sdb2/music/flac/files
shadup mv "Roxy.Music.Avalon.1982.UIGY-9672.SHM-SACD.DSD" "Roxy Music - Avalon"
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

No `VA -` here — these are main-artist albums. Details in `SKILL.md`.

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

## VA only for true collections

`VA -` = multi-artist compilation / anthology with no single primary artist
(e.g. `VA - Verve Remixed- The First Ladies 2013`, `VA - DJ-Kicks- DJ Cam`).

Main artist + guests/collaborators → still `Artist - Album` (Pixies, Pogues,
…). Do not refile those under `VA -`.

**Pogues best-ofs (live inconsistency):** both are single-artist compilations;
neither should be `VA -`. Strip artist `The` as usual.

| On disk now | Homogeneous target |
|-------------|-----------|
| `The Pogues - The Rest of the Best` | `Pogues - The Rest of the Best` |
| `VA - The Best of The Pogues` | `Pogues - The Best of The Pogues` |

MusicBrainz artist remains `The Pogues` in sidecars; dirname uses `Pogues`.

---

## Series already sanitized in-tree

Existing pattern to match:

- `VA - DJ-Kicks- DJ Cam`
- `Erlend Øye - DJ-Kicks- Erlend Øye`

MusicBrainz may still say `DJ-Kicks: Kid Loco`. Prefer the hyphenated series
form already used on disk; do not reintroduce `:`.

---

## Cue-driven collection

Album: `1973 - Verve Jazzclub - Verve Records Jazz Box [10LP]`

Use sidecar priority first; raw cue is for track `FILE` / multi-performer layout
when higher tiers lack tracks. Kind = collection/VA. Keep year + series prefix
from dirname when browsing tokens help.

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
album dir renames (`shadup mv`) run `shadup refresh-extracted-tags`, and prefer
`;`-namespaced tags (e.g. `artist;name`) without `:` in values when grooming
metadata (related: musicology tag grooming).
