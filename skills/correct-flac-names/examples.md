# Examples: correct FLAC names

Store root used below: `/mnt/sdb2/music/flac/files/`. Musicology:
`../bin/musicology` (utils sibling).

Path shapes to look for under an album dir:

| Path | Role |
|------|------|
| `SPECS/*.cue` | Rip cue (SACD / scene); primary TITLE/PERFORMER |
| `SPECS/*iNFO*.txt`, `SPECS/*.txt` | Secondary hints only |
| `.meta.cue.json` / `.meta.txt.json` | Often already parsed from SPECS |
| `.meta.musicbrainz.json` etc. | Provider sidecars |
| `.meta.combined.json` | Merged export (may be thin) |
| Track symlinks / `*.flac` / `*.dsf` | Current filenames (always a candidate) |

Skip `_tags/` and `data/` when surveying.

---

## Colon in album dirname (P0)

**Before:** `VA - Verve Remixed: The First Ladies 2013`

Live offender under the store root (illegal `:` for Samba/VFAT).

Sources (as of survey):

| Source | Artist | Album |
|--------|--------|-------|
| dirname | VA | Verve Remixed: The First Ladies (+ year `2013`) |
| `.meta.musicbrainz.json` `metadata` | Various Artists | Verve Remixed: The First Ladies |
| `.meta.{discogs,lastfm,johan}.json` `local` | VA | Verve Remixed: The First Ladies |
| cue | (none in album dir) | — |

Tracks are still scene-style
(`01-ella_fitzgerald-too_darn_hot_(rac_mix).flac`) — optional follow-up;
dirname P0 comes first.

Resolution: keep tree convention `VA` (not MusicBrainz `Various Artists`);
keep year suffix; VFAT-sanitize `:` → `-` (match in-tree `DJ-Kicks-` form).

**After (dir):** `VA - Verve Remixed- The First Ladies 2013`

```text
DIR  VA - Verve Remixed: The First Ladies 2013
  ->  VA - Verve Remixed- The First Ladies 2013
```

---

## Usenet / scene dotted rip name (pop-rock)

**Before:** `Roxy.Music.Avalon.1982.UIGY-9672.SHM-SACD.DSD`

Usenet/scene naming: dots for spaces, catalog + format tokens glued on.
VFAT-safe already, but **incorrect** vs pop/rock convention.

Sources:

| Source | Artist | Album |
|--------|--------|-------|
| dirname | (dotted blob) | — |
| `SPECS/…Avalon….cue` | Roxy Music | Avalon |
| `.meta.cue.json` / `.meta.txt.json` | Roxy Music | Avalon |
| musicbrainz / discogs / lastfm | (empty) | — |

Cue also has `FILE "Roxy Music - Avalon.dff"` — good target shape.
Tracks on disk are already humanish (`01 Roxy Music more than this.dsf`) but
titles are un-titlecased; optional cleanup after the album dir.

Resolution: cue/meta agree on `Roxy Music` / `Avalon`; drop rip noise
(`UIGY-9672`, `SHM-SACD`, `DSD`); year optional if useful for browsing.

**After (dir):** `Roxy Music - Avalon` (or `Roxy Music - Avalon (1982)` if year kept)

```text
DIR  Roxy.Music.Avalon.1982.UIGY-9672.SHM-SACD.DSD
  ->  Roxy Music - Avalon
```

Same pattern for siblings:
`Roxy.Music.Siren.1975.…`, `Roxy.Music.Country.Life.1974.…`, etc.

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

Cue top-level `TITLE "Verve Records Jazz Box"`; per-track different
`PERFORMER`s. Kind = collection/VA. Keep year + series prefix from dirname;
track files follow cue `FILE` / `TITLE` after sanitize.

---

## Classical subtitle

**Before (meta):** `Puccini: Greatest Hits`  
**In-tree form:** `Giacomo Puccini - Puccini- Greatest Hits`

Sanitize `:` → `-`; keep composer-forward dirname convention.

---

## SPECS rip (generic)

Same class as Avalon: dotted scene dirname + `SPECS/*.cue`, e.g.
`Miles.Davis.Kind.Of.Blue.2001.HYBRiD.2.0.CS-64935.SACD.DSD` →
`Miles Davis - Kind of Blue` (edition token only if needed to disambiguate).

---

## Tag mirror note

`_tags/album/DJ-Kicks: DJ Cam` can still contain `:` even when the real album
dir uses `-`. Fixing album dirs does not by itself rewrite tag strings; after
renames run `shadup refresh-extracted-tags`, and prefer `;`-namespaced tags
without `:` in values when grooming metadata (related: musicology tag grooming).
