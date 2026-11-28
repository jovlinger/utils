
See the work for volumeio; api usage

# volumeio fork was lost from gmk. reinstanted, rework. 

## todo:8b603c9c

Better use of the MPD API so Volumio does not ask for the whole library in one string. `listAlbums` uses `list album group albumartist` (one line per album name) instead of `search album ""`. Branch `8b603c9c-factor-list-albums` at `sha:e26b1bdd`.

2026-11-09 SHD measure (overlay `/volumio` running that `index.js`): after MPD was restarted and Volumio reconnected, `albums://` returned 1708 items in 0.45s; main Node RSS stayed about 111-114 MB (earlier peak about 123 MB). Full `mpc update` finished at 7708 songs. No journal heap abort. Deploy used `volumiooem` SSH; file install of `index.js` when on-device `git fetch` was blocked.

## todo:d6d78baa

MPD indexer work. Walk real directories first. Follow a symlink only when its target is not already indexed, including when that symlink is the only path (another drive counts). Do not trace a symlink back into an album folder that was already indexed, and do not store a second copy of those songs. Leaving MPD unchanged is also a valid finish, because the factored queries above already keep Node's replies small.
