# third_party

## MPD (dont-walk fork)

Local builds use a checkout of `jovlinger/MPD` branch `d6d78baa-dontwalk`
(not vendored in this repo):

```bash
git clone --branch d6d78baa-dontwalk git@github.com:jovlinger/MPD.git third_party/MPD
```

That branch adds the database-update don't-walk set (real directories before
symlinks; skip already-indexed real paths). macOS build notes: force bundled
fmt (`meson setup --force-fallback-for=fmt`), pass boost/libid3tag/icu include
and link paths from Homebrew.
