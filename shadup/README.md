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
