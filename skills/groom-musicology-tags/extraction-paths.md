# Extraction paths (deterministic)

Prefer the **normalized sidecar** (`schema` 1). Raw API blobs exist only when
`scan.py --include-raw` was used (`metadata` does not store `raw` in the default
corpus under `/mnt/sdb2/music/flac/files`).

Code source of truth: `../bin/musicology/providers.py`.

## Sidecar (all providers)

File: `.meta.<provider>.json`

| Field | JSON path | Emits |
|-------|-----------|--------|
| Artist | `$.metadata.artist` | `artist;{slug}` |
| Album | `$.metadata.album` | `album;{slug}` |
| Year | `$.metadata.year` | `year;{YYYY}` (take first 4 digits if ISO date) |
| Genres | `$.metadata.genres[*]` | via synonym map |
| Tags | `$.metadata.tags[*]` | via synonym map |
| Track title | `$.metadata.tracks[*].title` | (naming skill; not a tag type here) |
| Local guesses | `$.local.artist_guess`, `$.local.album_guess`, `$.local.year_guess` | fallbacks only |

`metatool --provider=ALL export-json` flattens to `{tag, genre, artist, album}`
with union of tags/genres and **shortest** artist/album — useful for naming,
but synonym maps still apply **per provider** before merge when grooming.

## MusicBrainz (raw, if present)

Written by `MusicBrainzProvider._to_metadata` as `raw.release` / `raw.search_hit`.

| Datum | Path under `raw` |
|-------|------------------|
| Artist credit | `release.artist-credit[*].artist.name` (joined) |
| Album title | `release.title` |
| Date | `release.date` |
| Country | `release.country` |
| Genres | `release.genre-list[*].name` |
| Tags | `release.tag-list[*].name` |
| Tracks | `release.medium-list[*].track-list[*].recording.title` |
| Release MBID | `release.id` |

Sidecar mapping already done: genres ← genre-list, tags ← tag-list.

## Discogs (raw, if present)

| Datum | Path under `raw` |
|-------|------------------|
| Artists | `release.artists[*].name` |
| Title | `release.title` |
| Year | `release.year` |
| Country | `release.country` |
| Genres | `release.genres[*]` → sidecar `metadata.genres` |
| Styles | `release.styles[*]` → sidecar `metadata.tags` |
| Tracklist | `release.tracklist[*].title` |
| Release id | `release.id` |

**Domain note:** Discogs “genres” are broad; “styles” are narrow. Both usually
become `genre;*` after synonyms; do not invent a separate `style` type.

## Last.fm (raw, if present)

| Datum | Path under `raw` |
|-------|------------------|
| Artist | `album.artist` (string or `{name,#text}`) |
| Album | `album.name` / `album.title` |
| Tags | `album.tags.tag[*]` or `album.toptags.tag[*]` (`name`, `count`) |
| Tracks | `album.tracks.track[*].name` |
| MBID | `album.mbid` |
| Release date | `album.releasedate` or `album.wiki.published` |

Provider splits sorted tag pairs: first N → `metadata.genres`, rest →
`metadata.tags`. **Re-classify** those strings (years/moods are not genres).

## Johan (local)

No upstream API. Fields are hand-edited via `metatool`. Treat values as already
near-canonical; map typos (`scandinivia` → `collection;scandinavia`) in
`synonyms/johan.json`.
