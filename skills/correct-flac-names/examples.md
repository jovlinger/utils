# Examples: correct FLAC names

Store root used below: `/mnt/sdb2/music/flac/files/`. Musicology:
`../bin/musicology` (utils sibling).

## Colon in album dirname (P0)

**Before:** `VA - Verve Remixed: The First Ladies 2013`

Sources:

| Source | Artist | Album |
|--------|--------|-------|
| dirname local guess | VA | Verve Remixed: The First Ladies |
| `.meta.musicbrainz.json` | Various Artists | Verve Remixed: The First Ladies |
| discogs/lastfm | (empty / thin) | — |

Resolution: shortest common album title among filled providers →
`Verve Remixed: The First Ladies`, then VFAT sanitize `:` → `-`.

**After:** `VA - Verve Remixed- The First Ladies 2013`

(Keep year suffix from dirname; keep `VA` if that is the tree convention for
compilations, even when MusicBrainz says `Various Artists`.)

## Series already sanitized in-tree

Existing pattern to match:

- `VA - DJ-Kicks- DJ Cam`
- `Erlend Øye - DJ-Kicks- Erlend Øye`

MusicBrainz may still say `DJ-Kicks: Kid Loco`. Prefer the hyphenated series
form already used on disk; do not reintroduce `:`.

## Cue-driven collection

Album: `1973 - Verve Jazzclub - Verve Records Jazz Box [10LP]`

Cue top-level `TITLE "Verve Records Jazz Box"`; per-track different
`PERFORMER`s. Kind = collection/VA. Keep year + series prefix from dirname;
track files follow cue `FILE` / `TITLE` after sanitize.

## Classical subtitle

**Before (meta):** `Puccini: Greatest Hits`  
**In-tree form:** `Giacomo Puccini - Puccini- Greatest Hits`

Sanitize `:` → `-`; keep composer-forward dirname convention.

## SPECS rip

Album dir may look like
`Miles.Davis.Kind.Of.Blue.2001.HYBRiD.2.0.CS-64935.SACD.DSD` with
`SPECS/*.cue` (`PERFORMER` / `TITLE` = Miles Davis / Kind of Blue).

Candidates: dotted rip name vs cue titles vs `.meta.*.json`. Prefer
pop/jazz convention `Miles Davis - Kind of Blue` (optionally keep edition
token if needed to disambiguate), all VFAT-safe. Track renames optional if
files are already `01. …`.

## Tag mirror note

`_tags/album/DJ-Kicks: DJ Cam` can still contain `:` even when the real album
dir uses `-`. Fixing album dirs does not by itself rewrite tag strings; after
renames run `shadup refresh-extracted-tags`, and prefer `;`-namespaced tags
without `:` in values when grooming metadata (related: musicology tag grooming).
